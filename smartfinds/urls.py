from django.contrib import admin
from django.urls import path, include
from . import views
from django.conf.urls.static import static
from django.conf import settings
from django.views.static import serve


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('store/', include('store.urls')),
    path('cart/', include('carts.urls')),
    path('accounts/', include('accounts.urls')),
    path('orders/', include('orders.urls')),
    path('virtual-tryon/', views.tryon_page, name='virtual_tryon'),
    # Shirts Try-On
    path('tryon/launch/', views.launch_tryon_app, name='launch_tryon_app'),
    path('tryon/stop/',   views.stop_tryon_app,   name='stop_tryon_app'),
    path('tryon/status/', views.tryon_status,     name='tryon_status'),

    path('photo-tryon/', views.photo_tryon, name='photo_tryon'),
    path('add-tryon-to-cart/', views.add_tryon_item_to_cart, name='add_tryon_item_to_cart'),

    # Glasses Try-On
    path('tryon/glasses/launch/',  views.launch_glasses_app, name='launch_glasses_app'),
    path('tryon/glasses/stop/',    views.stop_glasses_app,   name='stop_glasses_app'),
    path('tryon/glasses/status/',  views.glasses_status,     name='glasses_status'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
