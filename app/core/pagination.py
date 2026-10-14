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
