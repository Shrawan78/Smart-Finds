from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from carts.models import CartItem
from .forms import OrderForm
import datetime
from .models import Order, Payment, OrderProduct, Refund
from orders.utils import render_to_pdf
import json
import stripe
import paypalrestsdk
import requests as http_requests
from .forms import RefundRequestForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from store.models import Product
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.conf import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

paypalrestsdk.configure({
    "mode": settings.PAYPAL_MODE,
    "client_id": settings.PAYPAL_CLIENT_ID,
    "client_secret": settings.PAYPAL_CLIENT_SECRET,
})

def send_order_confirmation_email(order, payment, ordered_products, subtotal, transID):
    context = {
        'order': order,
        'payment': payment,
        'ordered_products': ordered_products,
        'subtotal': subtotal,
        'transID': transID,
        'order_number': order.order_number,
    }
    pdf_bytes = render_to_pdf('orders/invoice_pdf.html', context)

    mail_subject = 'Thank you for your order!'
    message = render_to_string('orders/order_received_email.html', {
        'user': order.user,
        'order': order,
    })

    email = EmailMessage(mail_subject, message, to=[order.user.email])
    if pdf_bytes:
        email.attach(
            filename=f'Invoice_{order.order_number}.pdf',
            content=pdf_bytes,
            mimetype='application/pdf',
        )
    email.send(fail_silently=False)

def payments(request):
    body = json.loads(request.body)

    order = Order.objects.get(user=request.user, is_ordered=False, order_number=body['orderID'])

    # Store transaction details inside Payment model
    payment = Payment(
        user=request.user,
        payment_id=body['transID'],
        payment_method=body['payment_method'],
        amount_paid=order.order_total,
        status=body['status'],
        amount_paid_usd=body.get('usdAmount'),
    )
    payment.save()

    order.payment = payment
    order.is_ordered = True
    order.save()

    # Move the cart items to Order Product table
    cart_items = CartItem.objects.filter(user=request.user)

    for item in cart_items:
        orderproduct = OrderProduct()
        orderproduct.order_id = order.id
        orderproduct.payment = payment
        orderproduct.user_id = request.user.id
        orderproduct.product_id = item.product_id
        orderproduct.quantity = item.quantity
        orderproduct.product_price = item.product.price
        orderproduct.ordered = True
        orderproduct.save()

        cart_item = CartItem.objects.get(id=item.id)
        product_variation = cart_item.variations.all()
        orderproduct = OrderProduct.objects.get(id=orderproduct.id)
        orderproduct.variations.set(product_variation)
        orderproduct.save()

        # Reduce the quantity of the sold products
        product = Product.objects.get(id=item.product_id)
        product.stock -= item.quantity
        product.save()

    # Clear cart
    CartItem.objects.filter(user=request.user).delete()

    # ── CHANGED: Send email with PDF invoice attached (PayPal) ───────────────
    ordered_products = OrderProduct.objects.filter(order_id=order.id)
    subtotal = sum(i.product_price * i.quantity for i in ordered_products)
    send_order_confirmation_email(order, payment, ordered_products, subtotal, payment.payment_id)
    # ─────────────────────────────────────────────────────────────────────────

    data = {
        'order_number': order.order_number,
        'transID': payment.payment_id,
    }
    return JsonResponse(data)


def place_order(request, total=0, quantity=0):
    current_user = request.user

    cart_items = CartItem.objects.filter(user=current_user)
    cart_count = cart_items.count()
    if cart_count <= 0:
        return redirect('store')

    grand_total = 0
    tax = 0
    for cart_item in cart_items:
        total += (cart_item.product.price * cart_item.quantity)
        quantity += cart_item.quantity
    tax = (2 * total) / 100
    grand_total = total + tax

    if request.method == "POST":
        form = OrderForm(request.POST)
        if form.is_valid():
            data = Order()
            data.user = current_user
            data.first_name = form.cleaned_data['first_name']
            data.last_name = form.cleaned_data['last_name']
            data.phone = form.cleaned_data['phone']
            data.email = form.cleaned_data['email']
            data.address_line_1 = form.cleaned_data['address_line_1']
            data.address_line_2 = form.cleaned_data['address_line_2']
            data.country = form.cleaned_data['country']
            data.state = form.cleaned_data['state']
            data.city = form.cleaned_data['city']
            data.order_note = form.cleaned_data['order_note']
            data.order_total = grand_total
            data.tax = tax
            data.ip = request.META.get('REMOTE_ADDR')
            data.save()

            # Generate order number
            yr = int(datetime.date.today().strftime('%Y'))
            dt = int(datetime.date.today().strftime('%d'))
            mt = int(datetime.date.today().strftime('%m'))
            d = datetime.date(yr, mt, dt)
            current_date = d.strftime("%Y%m%d")
            order_number = current_date + str(data.id)
            data.order_number = order_number
            data.save()

            order = Order.objects.get(user=current_user, is_ordered=False, order_number=order_number)
            context = {
                'order': order,
                'cart_items': cart_items,
                'total': total,
                'tax': tax,
                'grand_total': grand_total,
                'STRIPE_PUBLISHABLE_KEY': settings.STRIPE_PUBLISHABLE_KEY,
                'PAYPAL_CLIENT_ID': settings.PAYPAL_CLIENT_ID,
            }
            return render(request, 'orders/payments.html', context)
    else:
        return redirect('checkout')


def order_complete(request):
    order_number = request.GET.get('order_number')
    transID = request.GET.get('payment_id')

    try:
        order = Order.objects.get(order_number=order_number, is_ordered=True)
        ordered_products = OrderProduct.objects.filter(order_id=order.id)

        subtotal = 0
        for i in ordered_products:
            subtotal += i.product_price * i.quantity

        payment = Payment.objects.get(payment_id=transID)

        context = {
            'order': order,
            'ordered_products': ordered_products,
            'order_number': order.order_number,
            'transID': payment.payment_id,
            'payment': payment,
            'subtotal': subtotal,
        }
        return render(request, 'orders/order_complete.html', context)
    except (Payment.DoesNotExist, Order.DoesNotExist):
        return redirect('home')


def stripe_payment(request):
    if request.method == 'POST':
        body = json.loads(request.body)
        order = Order.objects.get(
            user=request.user,
            is_ordered=False,
            order_number=body['orderID']
        )

        try:
            # Use the USD amount sent from the frontend (converted from NPR)
            usd_amount = float(body.get('usdAmount', round(order.order_total / 155, 2)))

            charge = stripe.PaymentIntent.create(
                amount=int(usd_amount * 100),  # Stripe expects cents
                currency='usd',
                payment_method=body['payment_method_id'],
                confirm=True,
                automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            )

            # Save payment record with both NPR and USD amounts
            payment = Payment(
                user=request.user,
                payment_id=charge.id,
                payment_method='Stripe',
                amount_paid=order.order_total,   # NPR
                status=charge.status,
                amount_paid_usd=usd_amount,      # USD ← saved for refunds
            )
            payment.save()

            order.payment = payment
            order.is_ordered = True
            order.save()

            # Move cart items to OrderProduct
            cart_items = CartItem.objects.filter(user=request.user)
            for item in cart_items:
                orderproduct = OrderProduct()
                orderproduct.order_id = order.id
                orderproduct.payment = payment
                orderproduct.user_id = request.user.id
                orderproduct.product_id = item.product_id
                orderproduct.quantity = item.quantity
                orderproduct.product_price = item.product.price
                orderproduct.ordered = True
                orderproduct.save()

                cart_item = CartItem.objects.get(id=item.id)
                product_variation = cart_item.variations.all()
                orderproduct = OrderProduct.objects.get(id=orderproduct.id)
                orderproduct.variations.set(product_variation)
                orderproduct.save()

                product = Product.objects.get(id=item.product_id)
                product.stock -= item.quantity
                product.save()

            CartItem.objects.filter(user=request.user).delete()

            ordered_products = OrderProduct.objects.filter(order_id=order.id)
            subtotal = sum(i.product_price * i.quantity for i in ordered_products)
            send_order_confirmation_email(order, payment, ordered_products, subtotal, payment.payment_id)

            return JsonResponse({
                'order_number': order.order_number,
                'transID': payment.payment_id,
            })

        except stripe.error.CardError as e:
            return JsonResponse({'error': str(e.user_message)}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


@login_required
def request_refund(request, order_number):
    try:
        order = Order.objects.get(
            order_number=order_number,
            user=request.user,
            is_ordered=True
        )
    except Order.DoesNotExist:
        messages.error(request, "Order not found.")
        return redirect('order_complete')

    # Block duplicate refund requests
    if hasattr(order, 'refund'):
        messages.warning(request, "You have already submitted a refund request for this order.")
        return redirect('order_complete')

    if request.method == 'POST':
        form = RefundRequestForm(request.POST)
        if form.is_valid():
            Refund.objects.create(
                order=order,
                user=request.user,
                reason=f"{form.cleaned_data['reason_category']}: {form.cleaned_data['reason_detail']}",
                status='Pending',
            )
            # Email the admin
            mail_subject = f"New Refund Request - Order #{order.order_number}"
            message = render_to_string('orders/refund_request_email.html', {
                'order': order,
                'user': request.user,
            })
            email = EmailMessage(mail_subject, message, to=[settings.DEFAULT_FROM_EMAIL])
            email.content_subtype = 'html'
            email.send()

            messages.success(request, "Your refund request has been submitted. We will review it shortly.")
            return redirect('order_complete')
    else:
        form = RefundRequestForm()

    return render(request, 'orders/request_refund.html', {
        'form': form,
        'order': order,
    })


@login_required
def process_refund(request, order_number):
    if not request.user.is_staff:
        messages.error(request, "Access denied.")
        return redirect('home')

    try:
        order = Order.objects.get(order_number=order_number)
        refund = order.refund
    except (Order.DoesNotExist, Refund.DoesNotExist):
        messages.error(request, "Order or refund not found.")
        return redirect('admin_refund_list')

    action = request.POST.get('action')  # 'approve' or 'reject'

    if action == 'approve':
        payment = order.payment
        try:
            if payment.payment_method == 'Stripe':
                stripe_refund = stripe.Refund.create(
                    payment_intent=payment.payment_id,
                )
                refund.refund_id = stripe_refund.id
                refund.status = 'Approved'
                refund.save()

            elif payment.payment_method == 'PayPal':
                # Get PayPal access token
                auth_response = http_requests.post(
                    'https://api-m.sandbox.paypal.com/v1/oauth2/token',  # change to api-m.paypal.com in live
                    headers={'Accept': 'application/json'},
                    data={'grant_type': 'client_credentials'},
                    auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
                )
                access_token = auth_response.json().get('access_token')

                if not access_token:
                    messages.error(request, "PayPal authentication failed.")
                    return redirect('admin_refund_list')

                 # ── LOOK UP THE CAPTURE FIRST ────────────────────────────
                lookup = http_requests.get(
                    f'https://api-m.sandbox.paypal.com/v2/payments/captures/{payment.payment_id}',
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {access_token}',
                    }
                )
                print("=== CAPTURE LOOKUP ===")
                print(f"Status: {lookup.status_code}")
                print(f"Body: {lookup.json()}")
                print("======================")
                # ────────────────────────────────────────────────────────

                refund_response = http_requests.post(
                    f'https://api-m.sandbox.paypal.com/v2/payments/captures/{payment.payment_id}/refund',
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {access_token}',
                    },
                    json={}
                )

                refund_data = refund_response.json()

                if refund_response.status_code == 201 and refund_data.get('status') == 'COMPLETED':
                    refund.refund_id = refund_data.get('id')
                    refund.status = 'Approved'
                    refund.save()
                else:
                    messages.error(request, f"PayPal refund failed: {refund_data.get('message', 'Unknown error')}")
                    return redirect('admin_refund_list')

            # Email customer — refund approved
            mail_subject = "Your Refund Has Been Approved"
            message = render_to_string('orders/refund_approved_email.html', {
                'user': order.user,
                'order': order,
                'refund': refund,
            })
            email = EmailMessage(mail_subject, message, to=[order.email])
            email.content_subtype = 'html'
            email.send()
            messages.success(request, f"Refund for Order #{order.order_number} approved successfully.")

        except stripe.error.StripeError as e:
            messages.error(request, f"Stripe error: {e.user_message}")

    elif action == 'reject':
        refund.status = 'Rejected'
        refund.save()

        # Email customer — refund rejected
        mail_subject = "Update on Your Refund Request"
        message = render_to_string('orders/refund_rejected_email.html', {
            'user': order.user,
            'order': order,
        })
        email = EmailMessage(mail_subject, message, to=[order.email])
        email.content_subtype = 'html'
        email.send()
        messages.info(request, f"Refund for Order #{order.order_number} has been rejected.")

    return redirect('admin_refund_list')


@login_required
def admin_refund_list(request):
    if not request.user.is_staff:
        messages.error(request, "Access denied.")
        return redirect('home')

    refunds = Refund.objects.all().select_related('order', 'user').order_by('-created_at')
    return render(request, 'orders/admin_refund_list.html', {'refunds': refunds})
