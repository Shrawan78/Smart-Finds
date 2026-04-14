from django import forms
from .models import Order

class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = {'first_name','last_name','phone','email','address_line_1','address_line_2','country','state','city','order_note'}

class RefundRequestForm(forms.Form):
    REASON_CHOICES = [
        ('defective', 'Product is defective'),
        ('not_as_described', 'Not as described'),
        ('wrong_item', 'Wrong item received'),
        ('not_received', 'Item not received'),
        ('other', 'Other'),
    ]
    reason_category = forms.ChoiceField(
        choices=REASON_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    reason_detail = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Please describe your issue in detail...'
        }),
        max_length=500
    )
