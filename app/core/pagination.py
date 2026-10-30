# The page sizes a user can choose for a paginated list (includes/pagination.html).
PAGE_SIZES = (5, 10, 20, 50)


def get_page_size(request, key, default):
    """The number of items per page of the list `key`: the one asked with ?per_page=, which is
    remembered in the session for that list, or else the one remembered, or `default`."""
    session_key = f'page_size_{key}'
    asked = request.GET.get('per_page', '')
    if asked.isdigit() and int(asked) in PAGE_SIZES:
        request.session[session_key] = int(asked)
    size = request.session.get(session_key, default)
    return size if size in PAGE_SIZES else default


def get_pagination_page_range(paginator, current_page):
    """Return first/last pages and a compact window around the current page."""
    if paginator.num_pages <= 5:
        return paginator.page_range

    page_range = [1]
    first_middle_page = max(2, current_page - 1)
    last_middle_page = min(paginator.num_pages - 1, current_page + 1)

    if first_middle_page > 2:
        page_range.append(paginator.ELLIPSIS)

    page_range.extend(range(first_middle_page, last_middle_page + 1))

    if last_middle_page < paginator.num_pages - 1:
        page_range.append(paginator.ELLIPSIS)

    page_range.append(paginator.num_pages)
    return page_range
