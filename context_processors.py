def webp_support(request):
    return {'ltk_webp': 'image/webp' in request.META.get('HTTP_ACCEPT', {})}