from django.urls import path

from . import views
from .models import Conversation

urlpatterns = [
    path('conversations/', views.ConversationListView.as_view(), name='chat-conversations'),
    path('conversations/direct/', views.DirectConversationView.as_view(), name='chat-direct'),
    path('conversations/node/', views.GroupConversationView.as_view(kind=Conversation.Kind.NODE),
         name='chat-node-thread'),
    path('conversations/direction/',
         views.GroupConversationView.as_view(kind=Conversation.Kind.DIRECTION),
         name='chat-direction-thread'),
    path('conversations/<str:pk>/messages/', views.MessageListCreateView.as_view(),
         name='chat-messages'),
    path('conversations/<str:pk>/read/', views.MarkReadView.as_view(), name='chat-read'),
    path('unread-count/', views.UnreadCountView.as_view(), name='chat-unread-count'),
    path('users/', views.UserDirectoryView.as_view(), name='chat-users'),
]
