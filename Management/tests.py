from django.test import TestCase
from Management.models import Book, BookImage, BookTransaction
from django.utils import timezone

class BookModelTest(TestCase):
    def setUp(self):
        self.book = Book.objects.create(
            title="Test Book",
            author="Test Author",
            description="Test Description",
            deposit_price=100.00,
            read_price=10.00
        )

    def test_book_creation(self):
        self.assertEqual(self.book.title, "Test Book")
        self.assertTrue(self.book.is_available)
        self.assertEqual(self.book.deposit_price, 100.00)

    def test_book_string_representation(self):
        self.assertEqual(str(self.book), "Test Book")

class BookTransactionModelTest(TestCase):
    def setUp(self):
        self.book = Book.objects.create(
            title="Test Book",
            author="Test Author",
            description="Test Description",
            deposit_price=100.00,
            read_price=10.00
        )
        self.transaction = BookTransaction.objects.create(
            book=self.book,
            customer_name="Test Customer",
            customer_email="test@example.com",
            customer_mobile="1234567890",
            status="Issued"
        )

    def test_transaction_creation(self):
        self.assertEqual(self.transaction.customer_name, "Test Customer")
        self.assertEqual(self.transaction.status, "Issued")
        self.assertEqual(self.transaction.book, self.book)

    def test_transaction_string_representation(self):
        expected_str = f"Test Book - test@example.com (Issued)"
        self.assertEqual(str(self.transaction), expected_str)
