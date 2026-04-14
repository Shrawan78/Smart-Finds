from django.urls import path
from . import views

urlpatterns = [
    path('place_order/',              views.place_order,        name='place_order'),
    path('payments/',                 views.payments,           name='payments'),
    path('stripe_payment/',           views.stripe_payment,     name='stripe_payment'),
    path('order_complete/',           views.order_complete,     name='order_complete'),

    path('refund/<str:order_number>/',         views.request_refund,   name='request_refund'),
    path('refund/<str:order_number>/process/', views.process_refund,   name='process_refund'),
    path('admin/refunds/',                     views.admin_refund_list, name='admin_refund_list'),
]
