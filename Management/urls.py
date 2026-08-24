from django.urls import path
from . import views

urlpatterns = [
    # Admin URLs
    path('books/', views.dashboard, name='dashboard'),
    path('login/', views.login, name='login'),
    path('logout/', views.logout, name='logout'),
    
    # Book URLs
    path('add_book/', views.add_book, name='add_book'),
    path('book/<int:book_id>/', views.view_book, name='view_book'),
    path('book/<int:book_id>/edit/', views.edit_book, name='edit_book'),
    path('book/<int:book_id>/delete/', views.delete_book, name='delete_book'),
    
    # Transaction URLs
    path('', views.transactions, name='transactions'),
    path('transactions/', views.all_transactions, name='all_transactions'),
    path('issue_book/', views.issue_book, name='issue_book'),
    path('return_book_page/', views.return_book_page, name='return_book_page'),
    path('transaction/<int:transaction_id>/', views.view_transaction, name='view_transaction'),
    path('transaction/<int:transaction_id>/return/', views.return_book, name='return_book'),
    path('transaction/return/', views.return_book_post, name='return_book_post'),
    
    # Customer URLs
    path('customers/', views.customers, name='customers'),
]
