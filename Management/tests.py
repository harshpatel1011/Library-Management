"""
In-depth test suite for the Book Library (issue / return / penalty) Django app.

Place this file next to models.py / views.py / urls.py in your app folder
and run:

    python manage.py test <your_app_name> -v 2

Covers:
    * Models      - defaults, __str__, relations, cascade deletes
    * URLs        - reverse() + resolve() for every named route
    * Auth        - session-based admin login/logout, access control on every view
    * Books       - dashboard search, add / view / edit / delete, image handling
    * Transactions- listing, search, issue, return (both endpoints), penalty maths
    * Customers   - aggregation + search
    * Known issues- @expectedFailure tests documenting bugs found in views.py
"""
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from unittest import expectedFailure

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from . import views
from .models import Book, BookImage, BookTransaction

# Valid 1x1 transparent GIF so ImageField is happy even if Pillow validates it.
GIF_BYTES = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04"
    b"\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)

TEMP_MEDIA_ROOT = tempfile.mkdtemp(prefix="library_test_media_")

ADMIN_USERNAME = "Harsh"
ADMIN_PASSWORD = "Patel@123"


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def make_gif(name="test.gif"):
    return SimpleUploadedFile(name, GIF_BYTES, content_type="image/gif")


class BaseTestCase(TestCase):
    """Utility helpers shared by every test class."""

    def login_admin(self):
        session = self.client.session
        session["admin_id"] = 1
        session.save()

    def make_book(self, **kwargs):
        defaults = dict(
            title="Clean Code",
            author="Robert Martin",
            description="A handbook of agile software craftsmanship.",
            deposit_price=Decimal("400.00"),
            read_price=Decimal("100.00"),
            penalty_per_day=Decimal("10.00"),
            is_available=True,
        )
        defaults.update(kwargs)
        return Book.objects.create(**defaults)

    def make_tx(self, book=None, **kwargs):
        """Create an *Issued* transaction (book is marked unavailable)."""
        book = book or self.make_book()
        defaults = dict(
            book=book,
            customer_name="Alice",
            customer_email="alice@example.com",
            customer_mobile="9999999999",
            status="Issued",
            expected_return_date=timezone.now() + timedelta(days=10),
        )
        defaults.update(kwargs)
        tx = BookTransaction.objects.create(**defaults)
        if defaults["status"] == "Issued":
            Book.objects.filter(pk=book.pk).update(is_available=False)
        return tx

    def flash_messages(self, response):
        return [(m.level_tag, str(m)) for m in get_messages(response.wsgi_request)]

    def assertFlash(self, response, level, text_fragment):
        msgs = self.flash_messages(response)
        self.assertTrue(
            any(lvl == level and text_fragment in text for lvl, text in msgs),
            f"Expected {level!r} message containing {text_fragment!r}, got {msgs}",
        )


# --------------------------------------------------------------------------- #
# MODEL TESTS
# --------------------------------------------------------------------------- #
class BookModelTests(BaseTestCase):
    def test_str_returns_title(self):
        self.assertEqual(str(self.make_book(title="Dune")), "Dune")

    def test_defaults(self):
        book = Book.objects.create(title="T", author="A", description="D")
        self.assertTrue(book.is_available)
        self.assertEqual(book.deposit_price, Decimal("0.00"))
        self.assertEqual(book.read_price, Decimal("0.00"))
        self.assertEqual(book.penalty_per_day, Decimal("10.00"))

    def test_decimal_fields_persist_precisely(self):
        book = self.make_book(read_price=Decimal("123.45"), deposit_price=Decimal("493.80"))
        book.refresh_from_db()
        self.assertEqual(book.read_price, Decimal("123.45"))
        self.assertEqual(book.deposit_price, Decimal("493.80"))

    def test_max_lengths(self):
        self.assertEqual(Book._meta.get_field("title").max_length, 200)
        self.assertEqual(Book._meta.get_field("author").max_length, 100)


class BookImageModelTests(BaseTestCase):
    @override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
    def test_str_and_related_name(self):
        book = self.make_book(title="Dune")
        img = BookImage.objects.create(book=book, image=make_gif())
        self.assertEqual(str(img), "Image for Dune")
        self.assertIn(img, book.images.all())
        self.assertTrue(img.image.name.startswith("book_images/"))

    @override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
    def test_images_deleted_with_book(self):
        book = self.make_book()
        BookImage.objects.create(book=book, image=make_gif("a.gif"))
        BookImage.objects.create(book=book, image=make_gif("b.gif"))
        self.assertEqual(BookImage.objects.count(), 2)
        book.delete()
        self.assertEqual(BookImage.objects.count(), 0)


class BookTransactionModelTests(BaseTestCase):
    def test_str(self):
        tx = self.make_tx(self.make_book(title="Dune"), customer_email="bob@x.com")
        self.assertEqual(str(tx), "Dune - bob@x.com (Issued)")

    def test_defaults(self):
        tx = BookTransaction.objects.create(
            book=self.make_book(), customer_name="Z", customer_email="z@z.com"
        )
        self.assertEqual(tx.status, "Issued")
        self.assertEqual(tx.penalty, Decimal("0.00"))
        self.assertIsNone(tx.return_date)
        self.assertIsNone(tx.expected_return_date)
        self.assertIsNone(tx.customer_mobile)
        self.assertIsNotNone(tx.issue_date)  # auto_now_add

    def test_status_choices(self):
        choices = [c[0] for c in BookTransaction.STATUS_CHOICES]
        self.assertEqual(choices, ["Issued", "Returned"])

    def test_related_name_transactions(self):
        book = self.make_book()
        tx = self.make_tx(book)
        self.assertIn(tx, book.transactions.all())

    def test_transactions_deleted_with_book(self):
        book = self.make_book()
        self.make_tx(book)
        book.delete()
        self.assertEqual(BookTransaction.objects.count(), 0)


# --------------------------------------------------------------------------- #
# URL TESTS
# --------------------------------------------------------------------------- #
class UrlTests(BaseTestCase):
    def test_named_routes_resolve_to_expected_views(self):
        cases = [
            ("dashboard", {}, views.dashboard),
            ("login", {}, views.login),
            ("logout", {}, views.logout),
            ("add_book", {}, views.add_book),
            ("view_book", {"book_id": 1}, views.view_book),
            ("edit_book", {"book_id": 1}, views.edit_book),
            ("delete_book", {"book_id": 1}, views.delete_book),
            ("transactions", {}, views.transactions),
            ("all_transactions", {}, views.all_transactions),
            ("issue_book", {}, views.issue_book),
            ("return_book_page", {}, views.return_book_page),
            ("view_transaction", {"transaction_id": 1}, views.view_transaction),
            ("return_book", {"transaction_id": 1}, views.return_book),
            ("return_book_post", {}, views.return_book_post),
            ("customers", {}, views.customers),
        ]
        for name, kwargs, view in cases:
            with self.subTest(route=name):
                url = reverse(name, kwargs=kwargs)
                self.assertIs(resolve(url).func, view)

    def test_non_integer_ids_do_not_match(self):
        # <int:book_id> converter should reject strings -> 404 (no view reached)
        base = reverse("view_book", kwargs={"book_id": 1}).replace("/1/", "/abc/")
        self.assertEqual(self.client.get(base).status_code, 404)


# --------------------------------------------------------------------------- #
# AUTHENTICATION TESTS
# --------------------------------------------------------------------------- #
class LoginLogoutTests(BaseTestCase):
    def test_login_page_renders_for_anonymous(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "login.html")

    def test_login_success_sets_session_and_redirects(self):
        response = self.client.post(
            reverse("login"), {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
        self.assertRedirects(response, reverse("transactions"), fetch_redirect_response=False)
        self.assertEqual(self.client.session.get("admin_id"), 1)
        self.assertFlash(response, "success", "Welcome back Admin Harsh")

    def test_login_wrong_password(self):
        response = self.client.post(
            reverse("login"), {"username": ADMIN_USERNAME, "password": "nope"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("admin_id", self.client.session)
        self.assertFlash(response, "error", "Invalid admin credentials")

    def test_login_wrong_username(self):
        response = self.client.post(
            reverse("login"), {"username": "someone", "password": ADMIN_PASSWORD}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("admin_id", self.client.session)

    def test_login_is_case_sensitive(self):
        response = self.client.post(
            reverse("login"), {"username": "harsh", "password": ADMIN_PASSWORD}
        )
        self.assertNotIn("admin_id", self.client.session)
        self.assertFlash(response, "error", "Invalid admin credentials")

    def test_login_missing_fields(self):
        response = self.client.post(reverse("login"), {})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("admin_id", self.client.session)

    def test_logged_in_admin_is_redirected_away_from_login(self):
        self.login_admin()
        response = self.client.get(reverse("login"))
        self.assertRedirects(response, reverse("transactions"), fetch_redirect_response=False)

    def test_session_with_wrong_admin_id_is_not_admin(self):
        session = self.client.session
        session["admin_id"] = 2
        session.save()
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)

    def test_logout_clears_session_and_redirects(self):
        self.login_admin()
        response = self.client.get(reverse("logout"))
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        self.assertNotIn("admin_id", self.client.session)
        self.assertFlash(response, "success", "Admin logged out")

    def test_logout_when_not_logged_in_is_harmless(self):
        response = self.client.get(reverse("logout"))
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)


class AccessControlTests(BaseTestCase):
    """Every protected view must bounce anonymous users to /login/."""

    def test_all_protected_views_redirect_anonymous_get(self):
        book = self.make_book()
        tx = self.make_tx(book)
        urls = [
            reverse("dashboard"),
            reverse("add_book"),
            reverse("view_book", args=[book.id]),
            reverse("edit_book", args=[book.id]),
            reverse("delete_book", args=[book.id]),
            reverse("transactions"),
            reverse("all_transactions"),
            reverse("issue_book"),
            reverse("return_book_page"),
            reverse("view_transaction", args=[tx.id]),
            reverse("return_book", args=[tx.id]),
            reverse("return_book_post"),
            reverse("customers"),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)

    def test_anonymous_post_cannot_mutate_data(self):
        book = self.make_book()
        tx = self.make_tx(book)

        self.client.post(reverse("delete_book", args=[book.id]))
        self.client.post(reverse("edit_book", args=[book.id]), {"title": "HACKED"})
        self.client.post(reverse("return_book", args=[tx.id]))
        self.client.post(reverse("return_book_post"), {"transaction_id": tx.id})
        self.client.post(reverse("add_book"), {"title": "X", "author": "Y", "description": "Z"})
        self.client.post(
            reverse("issue_book"),
            {"book_id": book.id, "customer_name": "x", "customer_email": "x@x.com"},
        )

        book.refresh_from_db()
        tx.refresh_from_db()
        self.assertEqual(book.title, "Clean Code")
        self.assertEqual(tx.status, "Issued")
        self.assertEqual(Book.objects.count(), 1)
        self.assertEqual(BookTransaction.objects.count(), 1)


# --------------------------------------------------------------------------- #
# BOOK VIEW TESTS
# --------------------------------------------------------------------------- #
@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class BookViewTests(BaseTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.login_admin()

    # ---- dashboard (/books/) ------------------------------------------------
    def test_dashboard_lists_books_newest_first(self):
        first = self.make_book(title="First")
        second = self.make_book(title="Second")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "manage_books.html")
        self.assertEqual(list(response.context["books"]), [second, first])
        self.assertTrue(response.context["admin"])

    def test_dashboard_search_by_title_and_author_case_insensitive(self):
        self.make_book(title="Python Tricks", author="Dan Bader")
        self.make_book(title="Django Unleashed", author="Andrew Pinkham")
        self.make_book(title="Other", author="PYTHONISTA Writer")

        resp = self.client.get(reverse("dashboard"), {"q": "python"})
        titles = {b.title for b in resp.context["books"]}
        self.assertEqual(titles, {"Python Tricks", "Other"})

        resp = self.client.get(reverse("dashboard"), {"q": "pinkham"})
        self.assertEqual([b.title for b in resp.context["books"]], ["Django Unleashed"])

    def test_dashboard_search_no_match(self):
        self.make_book()
        resp = self.client.get(reverse("dashboard"), {"q": "zzzzz"})
        self.assertEqual(len(resp.context["books"]), 0)

    def test_dashboard_empty_query_returns_everything(self):
        self.make_book(title="A")
        self.make_book(title="B")
        resp = self.client.get(reverse("dashboard"), {"q": ""})
        self.assertEqual(len(resp.context["books"]), 2)

    # ---- add_book -----------------------------------------------------------
    def test_add_book_get_renders_form(self):
        response = self.client.get(reverse("add_book"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "add_book.html")

    def test_add_book_creates_book_with_deposit_four_times_read_price(self):
        response = self.client.post(
            reverse("add_book"),
            {"title": "New", "author": "Auth", "description": "Desc", "read_price": "50"},
        )
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        book = Book.objects.get(title="New")
        self.assertEqual(book.read_price, Decimal("50.00"))
        self.assertEqual(book.deposit_price, Decimal("200.00"))
        self.assertTrue(book.is_available)
        self.assertFlash(response, "success", "Book added successfully")

    def test_add_book_decimal_read_price(self):
        self.client.post(
            reverse("add_book"),
            {"title": "D", "author": "A", "description": "x", "read_price": "12.50"},
        )
        book = Book.objects.get(title="D")
        self.assertEqual(book.deposit_price, Decimal("50.00"))

    def test_add_book_without_read_price_defaults_to_zero(self):
        self.client.post(
            reverse("add_book"), {"title": "Free", "author": "A", "description": "x"}
        )
        book = Book.objects.get(title="Free")
        self.assertEqual(book.read_price, Decimal("0.00"))
        self.assertEqual(book.deposit_price, Decimal("0.00"))

    def test_add_book_with_multiple_images(self):
        self.client.post(
            reverse("add_book"),
            {
                "title": "Pics",
                "author": "A",
                "description": "x",
                "read_price": "10",
                "images": [make_gif("one.gif"), make_gif("two.gif")],
            },
        )
        book = Book.objects.get(title="Pics")
        self.assertEqual(book.images.count(), 2)

    def test_add_book_without_images(self):
        self.client.post(
            reverse("add_book"),
            {"title": "NoPics", "author": "A", "description": "x", "read_price": "10"},
        )
        self.assertEqual(Book.objects.get(title="NoPics").images.count(), 0)

    # ---- view_book ----------------------------------------------------------
    def test_view_book_shows_transactions_newest_first(self):
        book = self.make_book()
        old = self.make_tx(book, customer_name="Old")
        new = self.make_tx(book, customer_name="New")
        BookTransaction.objects.filter(pk=old.pk).update(
            issue_date=timezone.now() - timedelta(days=5)
        )
        response = self.client.get(reverse("view_book", args=[book.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "view_book.html")
        self.assertEqual(response.context["book"], book)
        self.assertEqual(list(response.context["transactions"]), [new, old])

    def test_view_book_not_found_redirects_with_error(self):
        response = self.client.get(reverse("view_book", args=[9999]))
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        self.assertFlash(response, "error", "Book not found")

    # ---- edit_book ----------------------------------------------------------
    def test_edit_book_get_renders_form(self):
        book = self.make_book()
        response = self.client.get(reverse("edit_book", args=[book.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "edit_book.html")
        self.assertEqual(response.context["book"], book)

    def test_edit_book_updates_fields_and_recalculates_deposit(self):
        book = self.make_book()
        response = self.client.post(
            reverse("edit_book", args=[book.id]),
            {"title": "Renamed", "author": "New Author", "description": "New desc", "read_price": "75"},
        )
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        book.refresh_from_db()
        self.assertEqual(book.title, "Renamed")
        self.assertEqual(book.author, "New Author")
        self.assertEqual(book.description, "New desc")
        self.assertEqual(book.read_price, Decimal("75.00"))
        self.assertEqual(book.deposit_price, Decimal("300.00"))
        self.assertFlash(response, "success", "Book updated successfully")

    def test_edit_book_adds_new_images(self):
        book = self.make_book()
        self.client.post(
            reverse("edit_book", args=[book.id]),
            {
                "title": book.title,
                "author": book.author,
                "description": book.description,
                "read_price": "10",
                "images": [make_gif("n1.gif"), make_gif("n2.gif")],
            },
        )
        self.assertEqual(book.images.count(), 2)

    def test_edit_book_deletes_selected_images_only(self):
        book = self.make_book()
        keep = BookImage.objects.create(book=book, image=make_gif("keep.gif"))
        drop = BookImage.objects.create(book=book, image=make_gif("drop.gif"))
        self.client.post(
            reverse("edit_book", args=[book.id]),
            {
                "title": book.title,
                "author": book.author,
                "description": book.description,
                "read_price": "10",
                "delete_gallery_images": [str(drop.id)],
            },
        )
        self.assertTrue(BookImage.objects.filter(pk=keep.pk).exists())
        self.assertFalse(BookImage.objects.filter(pk=drop.pk).exists())

    def test_edit_book_not_found(self):
        response = self.client.get(reverse("edit_book", args=[9999]))
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        self.assertFlash(response, "error", "Book not found")

    # ---- delete_book --------------------------------------------------------
    def test_delete_book_post_deletes(self):
        book = self.make_book()
        response = self.client.post(reverse("delete_book", args=[book.id]))
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        self.assertFalse(Book.objects.filter(pk=book.pk).exists())
        self.assertFlash(response, "success", "Book deleted successfully")

    def test_delete_book_get_does_not_delete(self):
        book = self.make_book()
        response = self.client.get(reverse("delete_book", args=[book.id]))
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        self.assertTrue(Book.objects.filter(pk=book.pk).exists())

    def test_delete_book_cascades_to_transactions_and_images(self):
        book = self.make_book()
        self.make_tx(book)
        BookImage.objects.create(book=book, image=make_gif())
        self.client.post(reverse("delete_book", args=[book.id]))
        self.assertEqual(BookTransaction.objects.count(), 0)
        self.assertEqual(BookImage.objects.count(), 0)

    def test_delete_book_not_found(self):
        response = self.client.post(reverse("delete_book", args=[9999]))
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        self.assertFlash(response, "error", "Book not found")


# --------------------------------------------------------------------------- #
# TRANSACTION LISTING / SEARCH TESTS
# --------------------------------------------------------------------------- #
class TransactionListingTests(BaseTestCase):
    def setUp(self):
        self.login_admin()

    def test_home_shows_only_latest_three_without_query(self):
        book = self.make_book()
        for i in range(5):
            self.make_tx(book, customer_name=f"C{i}", status="Returned")
        response = self.client.get(reverse("transactions"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard.html")
        self.assertEqual(len(response.context["transactions"]), 3)

    def test_home_latest_three_are_ordered_newest_first(self):
        book = self.make_book()
        txs = [self.make_tx(book, customer_name=f"C{i}", status="Returned") for i in range(4)]
        for i, tx in enumerate(txs):
            BookTransaction.objects.filter(pk=tx.pk).update(
                issue_date=timezone.now() - timedelta(days=10 - i)
            )
        shown = list(self.client.get(reverse("transactions")).context["transactions"])
        self.assertEqual([t.pk for t in shown], [txs[3].pk, txs[2].pk, txs[1].pk])

    def test_home_search_bypasses_three_item_limit(self):
        book = self.make_book(title="Searchable")
        for i in range(5):
            self.make_tx(book, customer_name=f"C{i}", status="Returned")
        response = self.client.get(reverse("transactions"), {"q": "Searchable"})
        self.assertEqual(len(response.context["transactions"]), 5)

    def test_home_search_by_name_email_and_title(self):
        b1 = self.make_book(title="Alpha")
        b2 = self.make_book(title="Beta")
        self.make_tx(b1, customer_name="Zed", customer_email="zed@x.com")
        self.make_tx(b2, customer_name="Yan", customer_email="yan@y.com")

        for q, expected in [("zed", 1), ("YAN", 1), ("y.com", 1), ("alpha", 1), ("nomatch", 0)]:
            with self.subTest(q=q):
                resp = self.client.get(reverse("transactions"), {"q": q})
                self.assertEqual(len(resp.context["transactions"]), expected)

    def test_home_context_available_books_and_issued_transactions(self):
        free = self.make_book(title="Free")
        busy = self.make_book(title="Busy")
        issued = self.make_tx(busy)
        self.make_tx(self.make_book(title="Done"), status="Returned")

        resp = self.client.get(reverse("transactions"))
        self.assertEqual([b.title for b in resp.context["available_books"]], ["Free"])
        self.assertEqual(list(resp.context["issued_transactions"]), [issued])
        self.assertNotIn(busy, resp.context["available_books"])
        self.assertIn(free, resp.context["available_books"])

    def test_home_available_books_sorted_by_title(self):
        for t in ["Charlie", "Alpha", "Bravo"]:
            self.make_book(title=t)
        resp = self.client.get(reverse("transactions"))
        self.assertEqual([b.title for b in resp.context["available_books"]], ["Alpha", "Bravo", "Charlie"])


class AllTransactionsTests(BaseTestCase):
    def setUp(self):
        self.login_admin()
        self.book = self.make_book(title="Dune")
        self.t1 = self.make_tx(
            self.book, customer_name="Alice", customer_email="a@x.com",
            customer_mobile="111", status="Returned",
        )
        self.t2 = self.make_tx(
            self.make_book(title="Emma"), customer_name="Bob",
            customer_email="b@x.com", customer_mobile="222",
        )

    def test_lists_all_transactions(self):
        resp = self.client.get(reverse("all_transactions"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "all_transactions.html")
        self.assertEqual(len(resp.context["transactions"]), 2)

    def test_search_across_title_name_email_mobile(self):
        cases = [("dune", 1), ("bob", 1), ("a@x.com", 1), ("222", 1), ("x.com", 2), ("zzz", 0)]
        for q, expected in cases:
            with self.subTest(q=q):
                resp = self.client.get(reverse("all_transactions"), {"q": q})
                self.assertEqual(len(resp.context["transactions"]), expected)

    def test_exact_filter_requires_all_three_params(self):
        resp = self.client.get(
            reverse("all_transactions"),
            {"name": "Alice", "email": "a@x.com", "mobile": "111"},
        )
        self.assertEqual(list(resp.context["transactions"]), [self.t1])

    def test_exact_filter_ignored_if_any_param_missing(self):
        resp = self.client.get(
            reverse("all_transactions"), {"name": "Alice", "email": "a@x.com"}
        )
        self.assertEqual(len(resp.context["transactions"]), 2)

    def test_exact_filter_is_exact_not_partial(self):
        resp = self.client.get(
            reverse("all_transactions"),
            {"name": "Ali", "email": "a@x.com", "mobile": "111"},
        )
        self.assertEqual(len(resp.context["transactions"]), 0)

    def test_search_and_exact_filter_combine(self):
        resp = self.client.get(
            reverse("all_transactions"),
            {"q": "dune", "name": "Bob", "email": "b@x.com", "mobile": "222"},
        )
        self.assertEqual(len(resp.context["transactions"]), 0)


class ViewTransactionTests(BaseTestCase):
    def setUp(self):
        self.login_admin()

    def test_view_transaction_renders(self):
        tx = self.make_tx()
        resp = self.client.get(reverse("view_transaction", args=[tx.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "view_transaction.html")
        self.assertEqual(resp.context["transaction"], tx)

    def test_view_transaction_not_found(self):
        resp = self.client.get(reverse("view_transaction", args=[9999]))
        self.assertRedirects(resp, reverse("dashboard"), fetch_redirect_response=False)
        self.assertFlash(resp, "error", "Transaction not found")


# --------------------------------------------------------------------------- #
# ISSUE BOOK TESTS
# --------------------------------------------------------------------------- #
class IssueBookTests(BaseTestCase):
    def setUp(self):
        self.login_admin()
        self.book = self.make_book()
        self.payload = {
            "book_id": self.book.id,
            "customer_name": "Alice",
            "customer_email": "alice@example.com",
            "customer_mobile": "9876543210",
        }

    def test_get_renders_form_with_available_books_and_issued_list(self):
        issued_book = self.make_book(title="Already Out")
        issued_tx = self.make_tx(issued_book)
        resp = self.client.get(reverse("issue_book"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "issue_book.html")
        self.assertEqual(list(resp.context["books"]), [self.book])
        self.assertEqual(list(resp.context["issued_transactions"]), [issued_tx])

    def test_issue_book_creates_transaction_and_marks_unavailable(self):
        resp = self.client.post(reverse("issue_book"), self.payload)
        self.assertRedirects(resp, reverse("transactions"), fetch_redirect_response=False)

        tx = BookTransaction.objects.get()
        self.assertEqual(tx.book, self.book)
        self.assertEqual(tx.customer_name, "Alice")
        self.assertEqual(tx.customer_email, "alice@example.com")
        self.assertEqual(tx.customer_mobile, "9876543210")
        self.assertEqual(tx.status, "Issued")
        self.assertIsNone(tx.return_date)
        self.assertEqual(tx.penalty, Decimal("0.00"))

        self.book.refresh_from_db()
        self.assertFalse(self.book.is_available)
        self.assertFlash(resp, "success", "Book issued to Alice successfully")

    def test_expected_return_date_is_ten_days_out(self):
        self.client.post(reverse("issue_book"), self.payload)
        tx = BookTransaction.objects.get()
        delta = tx.expected_return_date - timezone.now()
        self.assertAlmostEqual(delta.total_seconds(), timedelta(days=10).total_seconds(), delta=10)

    def test_issue_without_mobile_stores_empty_string(self):
        del self.payload["customer_mobile"]
        self.client.post(reverse("issue_book"), self.payload)
        self.assertEqual(BookTransaction.objects.get().customer_mobile, "")

    def test_cannot_issue_unavailable_book(self):
        self.book.is_available = False
        self.book.save()
        resp = self.client.post(reverse("issue_book"), self.payload)
        self.assertRedirects(resp, reverse("issue_book"), fetch_redirect_response=False)
        self.assertEqual(BookTransaction.objects.count(), 0)
        self.assertFlash(resp, "error", "already issued or unavailable")

    def test_cannot_issue_same_book_twice(self):
        self.client.post(reverse("issue_book"), self.payload)
        self.client.post(reverse("issue_book"), {**self.payload, "customer_name": "Bob"})
        self.assertEqual(BookTransaction.objects.count(), 1)

    def test_issue_nonexistent_book(self):
        self.payload["book_id"] = 9999
        resp = self.client.post(reverse("issue_book"), self.payload)
        self.assertRedirects(resp, reverse("dashboard"), fetch_redirect_response=False)
        self.assertEqual(BookTransaction.objects.count(), 0)
        self.assertFlash(resp, "error", "Book not found")

    def test_issue_without_book_id(self):
        del self.payload["book_id"]
        resp = self.client.post(reverse("issue_book"), self.payload)
        self.assertRedirects(resp, reverse("dashboard"), fetch_redirect_response=False)
        self.assertEqual(BookTransaction.objects.count(), 0)


# --------------------------------------------------------------------------- #
# RETURN BOOK TESTS  (exercises BOTH return endpoints with the same scenarios)
# --------------------------------------------------------------------------- #
class ReturnBookTests(BaseTestCase):
    def setUp(self):
        self.login_admin()

    # Both endpoints implement identical logic; test them via one helper.
    def _return(self, tx, via):
        if via == "path":
            return self.client.post(reverse("return_book", args=[tx.id]))
        return self.client.post(reverse("return_book_post"), {"transaction_id": tx.id})

    VIA = ("path", "post")

    def test_return_page_lists_issued_and_returned(self):
        issued = self.make_tx(self.make_book(title="Out"))
        returned = self.make_tx(self.make_book(title="Back"), status="Returned",
                                return_date=timezone.now())
        resp = self.client.get(reverse("return_book_page"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "return_book.html")
        self.assertEqual(list(resp.context["issued_transactions"]), [issued])
        self.assertEqual(list(resp.context["returned_transactions"]), [returned])

    def test_return_on_time_marks_returned_no_penalty(self):
        for via in self.VIA:
            with self.subTest(via=via):
                tx = self.make_tx(self.make_book(title=f"B-{via}"))
                resp = self._return(tx, via)
                self.assertRedirects(resp, reverse("transactions"), fetch_redirect_response=False)

                tx.refresh_from_db()
                self.assertEqual(tx.status, "Returned")
                self.assertIsNotNone(tx.return_date)
                self.assertEqual(tx.penalty, Decimal("0.00"))
                tx.book.refresh_from_db()
                self.assertTrue(tx.book.is_available)
                self.assertFlash(resp, "success", "Book returned by Alice!")

    def test_late_return_calculates_penalty_per_full_day(self):
        # 3 days + 2 hours late -> 3 whole days * 10.00 = 30.00
        for via in self.VIA:
            with self.subTest(via=via):
                tx = self.make_tx(
                    self.make_book(title=f"Late-{via}"),
                    expected_return_date=timezone.now() - timedelta(days=3, hours=2),
                )
                resp = self._return(tx, via)
                tx.refresh_from_db()
                self.assertEqual(tx.penalty, Decimal("30.00"))
                self.assertFlash(resp, "success", "Penalty of 30")

    def test_return_less_than_one_day_late_has_no_penalty(self):
        for via in self.VIA:
            with self.subTest(via=via):
                tx = self.make_tx(
                    self.make_book(title=f"Slight-{via}"),
                    expected_return_date=timezone.now() - timedelta(hours=23),
                )
                resp = self._return(tx, via)
                tx.refresh_from_db()
                self.assertEqual(tx.penalty, Decimal("0.00"))
                self.assertEqual(tx.status, "Returned")
                msgs = self.flash_messages(resp)
                self.assertFalse(any("Penalty" in m for _, m in msgs))

    def test_penalty_uses_the_books_own_rate(self):
        for via in self.VIA:
            with self.subTest(via=via):
                book = self.make_book(title=f"Pricey-{via}", penalty_per_day=Decimal("25.50"))
                tx = self.make_tx(
                    book, expected_return_date=timezone.now() - timedelta(days=2, hours=1)
                )
                self._return(tx, via)
                tx.refresh_from_db()
                self.assertEqual(tx.penalty, Decimal("51.00"))

    def test_return_without_expected_date_has_no_penalty(self):
        for via in self.VIA:
            with self.subTest(via=via):
                tx = self.make_tx(self.make_book(title=f"NoDue-{via}"), expected_return_date=None)
                self._return(tx, via)
                tx.refresh_from_db()
                self.assertEqual(tx.penalty, Decimal("0.00"))
                self.assertEqual(tx.status, "Returned")

    def test_return_exactly_on_deadline_boundary_is_not_penalised(self):
        tx = self.make_tx(expected_return_date=timezone.now() + timedelta(seconds=30))
        self._return(tx, "path")
        tx.refresh_from_db()
        self.assertEqual(tx.penalty, Decimal("0.00"))

    def test_return_path_get_does_not_change_anything(self):
        tx = self.make_tx()
        resp = self.client.get(reverse("return_book", args=[tx.id]))
        self.assertRedirects(resp, reverse("transactions"), fetch_redirect_response=False)
        tx.refresh_from_db()
        self.assertEqual(tx.status, "Issued")
        tx.book.refresh_from_db()
        self.assertFalse(tx.book.is_available)

    def test_return_post_endpoint_get_does_not_change_anything(self):
        tx = self.make_tx()
        resp = self.client.get(reverse("return_book_post"))
        self.assertRedirects(resp, reverse("transactions"), fetch_redirect_response=False)
        tx.refresh_from_db()
        self.assertEqual(tx.status, "Issued")

    def test_return_nonexistent_transaction(self):
        resp = self.client.post(reverse("return_book", args=[9999]))
        self.assertRedirects(resp, reverse("dashboard"), fetch_redirect_response=False)
        self.assertFlash(resp, "error", "Transaction not found")

    def test_return_post_nonexistent_transaction(self):
        resp = self.client.post(reverse("return_book_post"), {"transaction_id": 9999})
        self.assertRedirects(resp, reverse("dashboard"), fetch_redirect_response=False)
        self.assertFlash(resp, "error", "Transaction not found")

    def test_return_post_missing_transaction_id(self):
        resp = self.client.post(reverse("return_book_post"), {})
        self.assertRedirects(resp, reverse("dashboard"), fetch_redirect_response=False)
        self.assertFlash(resp, "error", "Transaction not found")

    def test_return_only_frees_the_related_book(self):
        tx1 = self.make_tx(self.make_book(title="One"))
        tx2 = self.make_tx(self.make_book(title="Two"), customer_email="two@x.com")
        self._return(tx1, "path")
        tx1.book.refresh_from_db()
        tx2.book.refresh_from_db()
        self.assertTrue(tx1.book.is_available)
        self.assertFalse(tx2.book.is_available)

    def test_book_can_be_reissued_after_return(self):
        book = self.make_book()
        tx = self.make_tx(book)
        self._return(tx, "path")
        resp = self.client.post(
            reverse("issue_book"),
            {"book_id": book.id, "customer_name": "Bob", "customer_email": "bob@x.com"},
        )
        self.assertRedirects(resp, reverse("transactions"), fetch_redirect_response=False)
        self.assertEqual(book.transactions.count(), 2)
        self.assertEqual(book.transactions.filter(status="Issued").count(), 1)


# --------------------------------------------------------------------------- #
# CUSTOMER VIEW TESTS
# --------------------------------------------------------------------------- #
class CustomersViewTests(BaseTestCase):
    def setUp(self):
        self.login_admin()
        # Alice: 3 transactions (1 issued, 2 returned)
        self.alice = dict(customer_name="Alice", customer_email="alice@x.com", customer_mobile="111")
        self.make_tx(self.make_book(title="B1"), status="Returned", **self.alice)
        self.make_tx(self.make_book(title="B2"), status="Returned", **self.alice)
        self.make_tx(self.make_book(title="B3"), status="Issued", **self.alice)
        # Bob: 1 transaction issued
        self.make_tx(
            self.make_book(title="B4"),
            customer_name="Bob", customer_email="bob@x.com", customer_mobile="222",
        )

    def _rows(self, **params):
        resp = self.client.get(reverse("customers"), params)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "customers.html")
        return {row["customer_email"]: row for row in resp.context["customers"]}

    def test_aggregates_per_customer(self):
        rows = self._rows()
        self.assertEqual(set(rows), {"alice@x.com", "bob@x.com"})
        self.assertEqual(rows["alice@x.com"]["total_books"], 3)
        self.assertEqual(rows["alice@x.com"]["currently_issued"], 1)
        self.assertEqual(rows["alice@x.com"]["returned_books"], 2)
        self.assertEqual(rows["bob@x.com"]["total_books"], 1)
        self.assertEqual(rows["bob@x.com"]["currently_issued"], 1)
        self.assertEqual(rows["bob@x.com"]["returned_books"], 0)

    def test_ordered_by_total_books_desc(self):
        resp = self.client.get(reverse("customers"))
        emails = [r["customer_email"] for r in resp.context["customers"]]
        self.assertEqual(emails, ["alice@x.com", "bob@x.com"])

    def test_search_by_name_email_mobile(self):
        self.assertEqual(set(self._rows(q="alice")), {"alice@x.com"})
        self.assertEqual(set(self._rows(q="BOB@X")), {"bob@x.com"})
        self.assertEqual(set(self._rows(q="222")), {"bob@x.com"})
        self.assertEqual(self._rows(q="nobody"), {})

    def test_same_email_with_different_name_is_a_separate_row(self):
        # values() groups on (email, name, mobile) so a typo creates a new "customer".
        self.make_tx(
            self.make_book(title="B5"),
            customer_name="Alice K", customer_email="alice@x.com", customer_mobile="111",
        )
        resp = self.client.get(reverse("customers"))
        alice_rows = [r for r in resp.context["customers"] if r["customer_email"] == "alice@x.com"]
        self.assertEqual(len(alice_rows), 2)


# --------------------------------------------------------------------------- #
# END-TO-END WORKFLOW
# --------------------------------------------------------------------------- #
@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class FullWorkflowTests(BaseTestCase):
    def test_login_add_issue_return_with_penalty_flow(self):
        # 1. Log in
        self.client.post(reverse("login"), {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        self.assertEqual(self.client.session.get("admin_id"), 1)

        # 2. Add a book
        self.client.post(
            reverse("add_book"),
            {"title": "E2E", "author": "Tester", "description": "flow", "read_price": "20",
             "images": [make_gif()]},
        )
        book = Book.objects.get(title="E2E")
        self.assertEqual(book.deposit_price, Decimal("80.00"))
        self.assertEqual(book.images.count(), 1)

        # 3. Issue it
        self.client.post(
            reverse("issue_book"),
            {"book_id": book.id, "customer_name": "Eve", "customer_email": "eve@x.com",
             "customer_mobile": "123"},
        )
        book.refresh_from_db()
        self.assertFalse(book.is_available)
        tx = BookTransaction.objects.get()

        # 4. Pretend it is 5 days + a bit overdue
        BookTransaction.objects.filter(pk=tx.pk).update(
            expected_return_date=timezone.now() - timedelta(days=5, hours=1)
        )

        # 5. Return it
        resp = self.client.post(reverse("return_book", args=[tx.id]), follow=True)
        self.assertEqual(resp.status_code, 200)
        tx.refresh_from_db()
        book.refresh_from_db()
        self.assertEqual(tx.status, "Returned")
        self.assertEqual(tx.penalty, Decimal("50.00"))
        self.assertTrue(book.is_available)

        # 6. Customer summary reflects it
        resp = self.client.get(reverse("customers"))
        row = resp.context["customers"][0]
        self.assertEqual(row["total_books"], 1)
        self.assertEqual(row["returned_books"], 1)
        self.assertEqual(row["currently_issued"], 0)

        # 7. Log out -> protected pages locked again
        self.client.get(reverse("logout"))
        self.assertRedirects(
            self.client.get(reverse("dashboard")), reverse("login"), fetch_redirect_response=False
        )


# --------------------------------------------------------------------------- #
# KNOWN ISSUES
# These document real bugs/weak spots in views.py. They are marked
# @expectedFailure so the suite stays green today, and will flag
# "unexpected success" once you fix the underlying problem - at which point
# simply remove the decorator.
# --------------------------------------------------------------------------- #
class KnownIssueTests(BaseTestCase):
    def setUp(self):
        self.login_admin()

    @expectedFailure
    def test_returning_an_already_returned_transaction_should_be_a_noop(self):
        """return_book never checks tx.status, so a second POST overwrites
        return_date/penalty and re-frees the book."""
        original = timezone.now() - timedelta(days=2)
        tx = self.make_tx(status="Returned", return_date=original)
        self.client.post(reverse("return_book", args=[tx.id]))
        tx.refresh_from_db()
        self.assertEqual(tx.return_date, original)

    @expectedFailure
    def test_add_book_with_blank_read_price_should_not_crash(self):
        """An empty string passes `request.POST.get('read_price', 0)` untouched
        and Decimal conversion raises ValidationError (HTTP 500)."""
        resp = self.client.post(
            reverse("add_book"),
            {"title": "Blank", "author": "A", "description": "x", "read_price": ""},
        )
        self.assertEqual(resp.status_code, 302)

    @expectedFailure
    def test_issue_book_should_reject_missing_customer_email(self):
        """No validation: a transaction is created with a blank email."""
        book = self.make_book()
        self.client.post(
            reverse("issue_book"), {"book_id": book.id, "customer_name": "NoEmail"}
        )
        self.assertEqual(BookTransaction.objects.count(), 0)

    @expectedFailure
    def test_add_book_should_reject_negative_price(self):
        self.client.post(
            reverse("add_book"),
            {"title": "Neg", "author": "A", "description": "x", "read_price": "-5"},
        )
        self.assertFalse(Book.objects.filter(title="Neg").exists())

    @expectedFailure
    def test_logout_should_not_be_triggerable_via_get(self):
        """State-changing action on GET (CSRF-able logout)."""
        self.client.get(reverse("logout"))
        self.assertIn("admin_id", self.client.session)
