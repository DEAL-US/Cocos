from django.test import RequestFactory, SimpleTestCase

from core.pagination import get_page_size


class PageSizeTests(SimpleTestCase):
    """The page size of a list is chosen with ?per_page= and remembered in the session for that list."""

    def request(self, session, **query):
        request = RequestFactory().get('/', query)
        request.session = session
        return request

    def test_the_default_until_a_size_is_chosen(self):
        self.assertEqual(get_page_size(self.request({}), 'samples', 10), 10)

    def test_a_chosen_size_is_remembered_for_that_list_only(self):
        session = {}
        self.assertEqual(get_page_size(self.request(session, per_page='20'), 'samples', 10), 20)
        self.assertEqual(get_page_size(self.request(session), 'samples', 10), 20)
        self.assertEqual(get_page_size(self.request(session), 'notifications', 10), 10)

    def test_sizes_not_offered_are_ignored(self):
        session = {}
        for asked in ('7', '0', '-5', 'all', '1000'):
            with self.subTest(asked):
                self.assertEqual(get_page_size(self.request(session, per_page=asked), 'samples', 10), 10)
        self.assertEqual(session, {})
