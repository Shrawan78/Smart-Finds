from django.contrib import admin, messages
from .models import Payment, Order, OrderProduct, Refund
import stripe
import requests as http_requests
from django.conf import settings

class OrderProductInline(admin.TabularInline):
    model = OrderProduct
    readonly_fields = ('payment', 'user', 'product', 'quantity', 'product_price', 'ordered')
    extra = 0

class orderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'full_name', 'phone', 'email', 'city', 'order_total', 'tax', 'status', 'is_ordered', 'created_at']
    list_filter = ['status', 'is_ordered']
    search_fields = ['order_number', 'first_name', 'last_name', 'phone', 'email']
    list_per_page = 20
    inlines = [OrderProductInline]

class RefundAdmin(admin.ModelAdmin):
    list_display    = ['order', 'user', 'status', 'refund_id', 'created_at']
    list_filter     = ['status']
    search_fields   = ['order__order_number', 'user__email', 'refund_id']
    readonly_fields = ['refund_id', 'created_at', 'updated_at']
    actions         = ['approve_refund', 'reject_refund']

    def approve_refund(self, request, queryset):
        for refund in queryset:
            if refund.status != 'Pending':
                self.message_user(request, f"Order {refund.order.order_number} is not pending.", messages.WARNING)
                continue

            payment = refund.order.payment

            try:
                if payment.payment_method == 'Stripe':
                    stripe.api_key = settings.STRIPE_SECRET_KEY
                    stripe_refund = stripe.Refund.create(
                        payment_intent=payment.payment_id,
                    )
                    refund.refund_id = stripe_refund.id
                    refund.status = 'Approved'
                    refund.save()
                    self.message_user(request, f"Stripe refund approved for Order {refund.order.order_number}.")

                elif payment.payment_method == 'PayPal':
                    auth_response = http_requests.post(
                        'https://api-m.sandbox.paypal.com/v1/oauth2/token',
                        headers={'Accept': 'application/json'},
                        data={'grant_type': 'client_credentials'},
                        auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
                    )
                    access_token = auth_response.json().get('access_token')

                    if not access_token:
                        self.message_user(request, "PayPal authentication failed.", messages.ERROR)
                        continue

                    refund_response = http_requests.post(
                        f'https://api-m.sandbox.paypal.com/v2/payments/captures/{payment.payment_id}/refund',
                        headers={
                            'Content-Type': 'application/json',
                            'Authorization': f'Bearer {access_token}',
                        },
                        json={}
                    )

                    refund_data = refund_response.json()

                    print("=== PAYPAL REFUND DEBUG ===")
                    print(f"Status Code: {refund_response.status_code}")
                    print(f"Capture ID: {payment.payment_id}")
                    print(f"Response: {refund_data}")
                    print("===========================")

                    if refund_response.status_code == 201 and refund_data.get('status') == 'COMPLETED':
                        refund.refund_id = refund_data.get('id')
                        refund.status = 'Approved'
                        refund.save()
                        self.message_user(request, f"PayPal refund approved for Order {refund.order.order_number}.")
                    else:
                        self.message_user(request, f"PayPal refund failed: {refund_data.get('message', 'Unknown error')}", messages.ERROR)

            except Exception as e:
                self.message_user(request, f"Error: {str(e)}", messages.ERROR)

    approve_refund.short_description = "Approve selected refunds (process payment)"

    def reject_refund(self, request, queryset):
        queryset.update(status='Rejected')
        self.message_user(request, "Selected refunds have been rejected.")

    reject_refund.short_description = "Reject selected refunds"

admin.site.register(Order, orderAdmin)
admin.site.register(Payment)
admin.site.register(OrderProduct)
admin.site.register(Refund, RefundAdmin)
