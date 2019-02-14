from django import template
from django.conf import settings
from djwepb.djwebp.models import WebPImage
from djwepb.djwebp.utils import make_image_key 
from django.core.cache import cache
try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse
from django.contrib.staticfiles import finders
from huey.contrib.djhuey import db_task

register = template.Library()

@register.simple_tag(takes_context=True)
def srcset(context, image, size, crop=None, retina=2, webp=False):
    """Generate srcset and sizes properties for an <img>. image should be
       a django image object, i.e. an instance of models.ImageField.
       size should be a (W, H) tuple or a WxH string. Returns srcset and sizes
       attributes for an <img> tag, wrapped in jinja2 Markup if available.
       Assumes the following:
       - the width component of size equals the img element's pixel width at
         browser size REFERENCE_WIDTH
       - between MOBILE_MAX and REFERENCE_WIDTH, the img resizes proportionally
       - below MOBILE_MAX, the img is 100% of the browser width
       - if image is not cropped, the thumbnail will be constrained by width,
         not height
    """

    if not image:
        return ''

    if isinstance(size, str):
        size = tuple(map(int, size.split('x')))
    w, h = size

    # standard size
    size_pairs = [(w, h)]

    # add retina thumbnail to srcset, but only if the source image is big
    # enough to warrant it
    if retina:
        retina_size = tuple(map(int, (w * retina, h * retina)))
        w_bigger = image.width > retina_size[0]
        h_bigger = image.height > retina_size[1]
        if w_bigger and h_bigger or not crop and (w_bigger or h_bigger):
            size_pairs.append(retina_size)

    # add mobile size if the original image is bigger, and if it's different
    # enough to be worth it
    mobile_w = MOBILE_MIN * 2
    if w > mobile_w * 1.2:
        size_pairs.append((mobile_w, int(mobile_w * h / w)))

    # no srcset required if there's only one size
    if len(size_pairs) <= 1:
        return ''
    imgs = (get_thumbnail(image, '{0}x{1}'.format(s[0], s[1]), crop=crop) for s in size_pairs)

    if webp:
        srcset = ', '.join('%s %sw' % (get_webp(context, img.url), img.width) for img in imgs)
    else:
        srcset = ', '.join('%s %sw' % (img.url, img.width) for img in imgs)

    # generate sizes - 100% below MOBILE_MAX, a pixel width above DESKTOP_MAX,
    # and a percentage in between
    # TODO account for actual resized image discrepancies here
    size_data = [
        # min, max, image size
        (None, MOBILE_MAX, '100vw'),
        (MOBILE_MAX + 1, DESKTOP_MAX,
         '%svw' % (round(float(w) / REFERENCE_WIDTH * 100, 2))),
        (DESKTOP_MAX + 1, None, '%spx' % (w * DESKTOP_MAX / REFERENCE_WIDTH))
    ]

    def make_size(data):
        min_px, max_px, size = data
        mq_list = []
        if min_px:
            mq_list.append('min-width: %spx' % min_px)
        if max_px:
            mq_list.append('max-width: %spx' % max_px)
        return '(%s) %s' % (') and ('.join(mq_list), size)

    sizes = ', '.join(map(make_size, size_data))

    return Markup('data-srcset="{0}" sizes="{1}"'.format(srcset, sizes))

srcset.is_safe = True

@register.simple_tag(takes_context=True)
def get_webp(context, image_path, quality=12):
    print('get_webp')
    try:
        supports_webp = context.get('ltk_webp', False)
    except KeyError:
        raise Exception("'webp_converterLTK.context_processors.webp_support' "
                        "needs to be added to your context processors.")
    if not supports_webp:
        print('WebP not supported')
        try: 
            finders.find(image_path)
            image_path = urlparse.urljoin(settings.STATIC_URL, image_path)
        except:
            pass
        return image_path
    return make_webp(image_path, quality) 

def make_webp(image_path, quality=12):
    print('****************')
    key = make_image_key(image_path, quality)
    webp_image_url = cache.get(key)
    if not webp_image_url:
        print('🚨 NOT IN CACHE (launching task)' + str(webp_image_url))
        createwptask(image_path, key, quality)
        return image_path
    else:
        print('✅  IN CACHE' + str(webp_image_url))
    return webp_image_url
    
@db_task()
def createwptask(image_path, key, quality=12):
    image_path = image_path.replace("static/", "")
    webp_image, _ = WebPImage.objects.get_or_create(image_path=image_path, quality=quality)
    webp_image.save_image()
    webp_image_url = webp_image.url
    print('🚨  RECREATING BACKGROUND' + str(webp_image_url))
    cache.set(key, webp_image_url)