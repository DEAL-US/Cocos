from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.pagination import get_pagination_page_range
from notifications.models import TaskNotification


def _get_current_user_notifications(request):
    return TaskNotification.objects.filter(user=request.user)


def _redirect_to_next(request):
    """Redirect to the 'next' URL only if it points to this site, to avoid open redirects."""
    next_url = request.POST.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect('notifications:list')


@login_required
def notifications_view(request):
    status_filter = request.GET.get('status', 'all')
    page_number = request.GET.get('page', '1')
    base_notifications = _get_current_user_notifications(request)
    notifications = base_notifications
    if status_filter == 'read':
        notifications = notifications.filter(is_read=True)
    elif status_filter == 'unread':
        notifications = notifications.filter(is_read=False)

    paginator = Paginator(notifications.order_by('-created_at'), 6)
    page_obj = paginator.get_page(page_number)

    context = {
        'notifications': page_obj.object_list,
        'pagination_page_range': get_pagination_page_range(paginator, page_obj.number),
        'pagination_url': reverse('notifications:list'),
        'pagination_query': f'status={status_filter}',
        'pagination_label': 'Notifications',
        'pagination_link_attribute': 'data-notification-page',
        'status_filter': status_filter,
        'page_obj': page_obj,
        'has_unread_notifications': base_notifications.filter(is_read=False).exists(),
    }
    template_name = 'notifications/_notifications_panel.html' if request.GET.get('partial') == '1' else 'notifications/notifications.html'
    return render(request, template_name, context)


@login_required
@require_POST
def mark_notification_read_view(request, notification_id):
    notification = get_object_or_404(_get_current_user_notifications(request), id=notification_id)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=['is_read'])
    return _redirect_to_next(request)


@login_required
@require_POST
def mark_all_notifications_read_view(request):
    _get_current_user_notifications(request).filter(is_read=False).update(is_read=True)
    return _redirect_to_next(request)
