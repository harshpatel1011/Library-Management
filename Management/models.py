from django.db import models

class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.CharField(max_length=100)
    description = models.TextField()
    is_available = models.BooleanField(default=True)
    deposit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    read_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    penalty_per_day = models.DecimalField(max_digits=10, decimal_places=2, default=10.00)

    def __str__(self):
        return self.title

class BookImage(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='book_images/')

    def __str__(self):
        return f"Image for {self.book.title}"

class BookTransaction(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='transactions')
    customer_name = models.CharField(max_length=100)
    customer_email = models.EmailField(default='')
    customer_mobile = models.CharField(max_length=15, blank=True, null=True)
    issue_date = models.DateTimeField(auto_now_add=True)
    return_date = models.DateTimeField(null=True, blank=True)
    expected_return_date = models.DateTimeField(null=True, blank=True)
    penalty = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    STATUS_CHOICES = [
        ('Issued', 'Issued'),
        ('Returned', 'Returned'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Issued')

    def __str__(self):
        return f"{self.book.title} - {self.customer_email} ({self.status})"
