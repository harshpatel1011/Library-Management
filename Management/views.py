from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q
from .models import Book, BookTransaction, BookImage
from datetime import timedelta


# Helper functions
def get_current_admin(request):
    admin_id = request.session.get("admin_id")
    if admin_id == 1:
        return True
    return False


# Admin Views
def login(request):
    if get_current_admin(request):
        return redirect("transactions")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        if username == "Harsh" and password == "Patel@123":
            request.session["admin_id"] = 1
            messages.success(request, f"Welcome back Admin {username}!")
            return redirect("transactions")
        else:
            messages.error(request, "Invalid admin credentials!")

    return render(request, "login.html")


def logout(request):
    if "admin_id" in request.session:
        del request.session["admin_id"]
    messages.success(request, "Admin logged out!")
    return redirect("login")


def dashboard(request):
    admin = get_current_admin(request)
    if not admin:
        return redirect("login")

    query = request.GET.get("q", "")
    if query:

        books = Book.objects.filter(
            Q(title__icontains=query) | Q(author__icontains=query)
        ).order_by("-id")
    else:
        books = Book.objects.all().order_by("-id")

    return render(
        request,
        "manage_books.html",
        {
            "admin": admin,
            "books": books,
        },
    )


def add_book(request):
    admin = get_current_admin(request)
    if not admin:
        return redirect("login")

    if request.method == "POST":
        title = request.POST.get("title")
        author = request.POST.get("author")
        description = request.POST.get("description")
        read_price = request.POST.get("read_price", 0)
        deposit_price = float(read_price) * 4 if read_price else 0
            
        book = Book.objects.create(
            title=title, 
            author=author, 
            description=description,
            deposit_price=deposit_price,
            read_price=read_price
        )

        images = request.FILES.getlist("images")
        for img in images:
            BookImage.objects.create(book=book, image=img)

        messages.success(request, "Book added successfully!")
        return redirect("dashboard")

    return render(request, "add_book.html", {"admin": admin})


def view_book(request, book_id):
    admin = get_current_admin(request)
    if not admin:
        return redirect("login")

    book = Book.objects.filter(id=book_id).first()
    if not book:
        messages.error(request, "Book not found.")
        return redirect("dashboard")
    transactions = book.transactions.all().order_by("-issue_date")
    return render(
        request,
        "view_book.html",
        {"admin": admin, "book": book, "transactions": transactions},
    )


def edit_book(request, book_id):
    admin = get_current_admin(request)
    if not admin:
        return redirect("login")

    book = Book.objects.filter(id=book_id).first()
    if not book:
        messages.error(request, "Book not found.")
        return redirect("dashboard")

    if request.method == "POST":
        book.title = request.POST.get("title")
        book.author = request.POST.get("author")
        book.description = request.POST.get("description")
        book.read_price = request.POST.get("read_price", 0)
        book.deposit_price = float(book.read_price) * 4 if book.read_price else 0

        book.save()

        # Handle image deletions
        delete_image_ids = request.POST.getlist("delete_gallery_images")
        if delete_image_ids:
            BookImage.objects.filter(id__in=delete_image_ids).delete()

        # Handle new images
        images = request.FILES.getlist("images")
        for img in images:
            BookImage.objects.create(book=book, image=img)

        messages.success(request, "Book updated successfully!")
        return redirect("dashboard")

    return render(request, "edit_book.html", {"admin": admin, "book": book})


def delete_book(request, book_id):
    admin = get_current_admin(request)
    if not admin:
        return redirect("login")

    book = Book.objects.filter(id=book_id).first()
    if not book:
        messages.error(request, "Book not found.")
        return redirect("dashboard")

    if request.method == "POST":
        book.delete()
        messages.success(request, "Book deleted successfully!")

    return redirect("dashboard")


# Transaction Views
def transactions(request):
    admin = get_current_admin(request)
    if not admin:
        return redirect("login")

    query = request.GET.get("q", "")
    if query:
        transactions = BookTransaction.objects.filter(
            Q(book__title__icontains=query)
            | Q(customer_name__icontains=query)
            | Q(customer_email__icontains=query)
        ).order_by("-issue_date")
    else:
        transactions = BookTransaction.objects.all().order_by("-issue_date")[:3]

    available_books = Book.objects.filter(is_available=True).order_by("title")
    issued_transactions = BookTransaction.objects.filter(status="Issued").order_by(
        "-issue_date"
    )

    return render(
        request,
        "dashboard.html",
        {
            "admin": admin,
            "transactions": transactions,
            "available_books": available_books,
            "issued_transactions": issued_transactions,
        },
    )


def all_transactions(request):
    admin = get_current_admin(request)
    if not admin:
        return redirect("login")

    query = request.GET.get("q", "")
    exact_name = request.GET.get("name", "")
    exact_email = request.GET.get("email", "")
    exact_mobile = request.GET.get("mobile", "")

    transactions = BookTransaction.objects.all().order_by("-issue_date")

    if query:
        transactions = transactions.filter(
            Q(book__title__icontains=query)
            | Q(customer_name__icontains=query)
            | Q(customer_email__icontains=query)
            | Q(customer_mobile__icontains=query)
        )

    if exact_name and exact_email and exact_mobile:
        transactions = transactions.filter(
            customer_name=exact_name,
            customer_email=exact_email,
            customer_mobile=exact_mobile,
        )
    return render(
        request, "all_transactions.html", {"admin": admin, "transactions": transactions}
    )


def issue_book(request):
    admin = get_current_admin(request)
    if not admin:
        return redirect("login")

    available_books = Book.objects.filter(is_available=True).order_by("title")

    if request.method == "POST":
        book_id = request.POST.get("book_id")
        customer_name = request.POST.get("customer_name")
        customer_email = request.POST.get("customer_email")
        customer_mobile = request.POST.get("customer_mobile", "")

        book = Book.objects.filter(id=book_id).first()
        if not book:
            messages.error(request, "Book not found.")
            return redirect("dashboard")

        if not book.is_available:
            messages.error(request, "This book is already issued or unavailable.")
            return redirect("issue_book")

        BookTransaction.objects.create(
            book=book,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_mobile=customer_mobile,
            status="Issued",
            expected_return_date=timezone.now() + timedelta(days=10)
        )
        book.is_available = False
        book.save()

        messages.success(request, f"Book issued to {customer_name} successfully!")
        return redirect("transactions")

    issued_transactions = BookTransaction.objects.filter(status="Issued").order_by(
        "-issue_date"
    )

    return render(
        request,
        "issue_book.html",
        {
            "admin": admin,
            "books": available_books,
            "issued_transactions": issued_transactions,
        },
    )


def return_book_page(request):
    admin = get_current_admin(request)
    if not admin:
        return redirect("login")

    issued_transactions = BookTransaction.objects.filter(status="Issued").order_by(
        "-issue_date"
    )
    returned_transactions = BookTransaction.objects.filter(status="Returned").order_by(
        "-return_date"
    )

    return render(
        request,
        "return_book.html",
        {
            "admin": admin,
            "issued_transactions": issued_transactions,
            "returned_transactions": returned_transactions,
        },
    )


def return_book(request, transaction_id):
    admin = get_current_admin(request)
    if not admin:
        return redirect("login")

    transaction = BookTransaction.objects.filter(id=transaction_id).first()
    if not transaction:
        messages.error(request, "Transaction not found.")
        return redirect("dashboard")

    if request.method == "POST":
        transaction.status = "Returned"
        transaction.return_date = timezone.now()
        
        penalty = 0.00
        if transaction.return_date and transaction.expected_return_date:
            if transaction.return_date > transaction.expected_return_date:
                days_late = (transaction.return_date - transaction.expected_return_date).days
                if days_late > 0:
                    penalty = days_late * transaction.book.penalty_per_day
        transaction.penalty = penalty
        
        transaction.save()

        book = transaction.book
        book.is_available = True
        book.save()

        if transaction.penalty > 0:
            messages.success(request, f"Book returned by {transaction.customer_name}! Penalty of {transaction.penalty} applied.")
        else:
            messages.success(request, f"Book returned by {transaction.customer_name}!")

    return redirect("transactions")


def return_book_post(request):
    admin = get_current_admin(request)
    if not admin:
        return redirect("login")

    if request.method == "POST":
        transaction_id = request.POST.get("transaction_id")
        transaction = BookTransaction.objects.filter(id=transaction_id).first()
        if not transaction:
            messages.error(request, "Transaction not found.")
            return redirect("dashboard")

        transaction.status = "Returned"
        transaction.return_date = timezone.now()
        
        penalty = 0.00
        if transaction.return_date and transaction.expected_return_date:
            if transaction.return_date > transaction.expected_return_date:
                days_late = (transaction.return_date - transaction.expected_return_date).days
                if days_late > 0:
                    penalty = days_late * transaction.book.penalty_per_day
        transaction.penalty = penalty
        
        transaction.save()

        book = transaction.book
        book.is_available = True
        book.save()

        if transaction.penalty > 0:
            messages.success(request, f"Book returned by {transaction.customer_name}! Penalty of {transaction.penalty} applied.")
        else:
            messages.success(request, f"Book returned by {transaction.customer_name}!")

    return redirect("transactions")


def view_transaction(request, transaction_id):
    admin = get_current_admin(request)
    if not admin:
        return redirect("login")

    transaction = BookTransaction.objects.filter(id=transaction_id).first()
    if not transaction:
        messages.error(request, "Transaction not found.")
        return redirect("dashboard")
    return render(
        request, "view_transaction.html", {"admin": admin, "transaction": transaction}
    )


def customers(request):
    admin = get_current_admin(request)
    if not admin:
        return redirect("login")

    query = request.GET.get("q", "")

    customers_qs = BookTransaction.objects.all()

    if query:
        customers_qs = customers_qs.filter(
            Q(customer_name__icontains=query)
            | Q(customer_email__icontains=query)
            | Q(customer_mobile__icontains=query)
        )

    customers_qs = (
        customers_qs.values("customer_email", "customer_name", "customer_mobile")
        .annotate(
            total_books=Count("id"),
            currently_issued=Count("id", filter=Q(status="Issued")),
            returned_books=Count("id", filter=Q(status="Returned")),
        )
        .order_by("-total_books")
    )

    return render(
        request, "customers.html", {"admin": admin, "customers": customers_qs}
    )
