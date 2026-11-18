
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User


class LogoutSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.user1 = User.objects.create_user(
            email='logout1@example.com',
            full_name='Logout User One',
            profession='Student',
            password='SecurePass123!',
        )

        self.user2 = User.objects.create_user(
            email='logout2@example.com',
            full_name='Logout User Two',
            profession='Developer',
            password='SecurePass123!',
        )

        self.user1_refresh = RefreshToken.for_user(self.user1)
        self.user2_refresh = RefreshToken.for_user(self.user2)

        self.user1_access = str(self.user1_refresh.access_token)

        self.logout_url = '/api/v1/auth/logout/'

    def authenticate_as_user1(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.user1_access}'
        )

    def test_user_can_logout_with_own_refresh_token(self):
        self.authenticate_as_user1()

        response = self.client.post(
            self.logout_url,
            {'refresh': str(self.user1_refresh)},
            format='json',
        )

        self.assertEqual(response.status_code, 205)

        with self.assertRaises(Exception):
            RefreshToken(str(self.user1_refresh))

    def test_user_cannot_logout_another_users_token(self):
        self.authenticate_as_user1()

        response = self.client.post(
            self.logout_url,
            {'refresh': str(self.user2_refresh)},
            format='json',
        )

        self.assertEqual(response.status_code, 403)

        # The other user's refresh token must remain valid.
        token = RefreshToken(str(self.user2_refresh))
        self.assertEqual(str(token['user_id']), str(self.user2.pk))

    def test_logout_requires_refresh_token(self):
        self.authenticate_as_user1()

        response = self.client.post(
            self.logout_url,
            {},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_logout_rejects_invalid_refresh_token(self):
        self.authenticate_as_user1()

        response = self.client.post(
            self.logout_url,
            {'refresh': 'invalid-refresh-token'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)


class RegistrationLoginAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.register_url = '/api/v1/auth/register/'
        self.login_url = '/api/v1/auth/login/'

        self.user = User.objects.create_user(
            email='existing@example.com',
            full_name='Existing Account',
            profession='Student',
            password='Violet!River#4829',
        )

    def test_user_can_register_successfully(self):
        response = self.client.post(
            self.register_url,
            {
                'full_name': 'New Test User',
                'email': 'newuser@example.com',
                'profession': 'Developer',
                'password': 'Orange!Mountain#5831',
                'confirm_password': 'Orange!Mountain#5831',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            User.objects.filter(email='newuser@example.com').exists()
        )

        created_user = User.objects.get(email='newuser@example.com')
        self.assertTrue(
            created_user.check_password('Orange!Mountain#5831')
        )

    def test_registration_rejects_duplicate_email_case_insensitively(self):
        response = self.client.post(
            self.register_url,
            {
                'full_name': 'Duplicate User',
                'email': 'EXISTING@EXAMPLE.COM',
                'profession': 'Student',
                'password': 'Orange!Mountain#5831',
                'confirm_password': 'Orange!Mountain#5831',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['email'][0],
            'A user with this email already exists.',
        )

    def test_registration_duplicate_email_shows_friendly_message(self):
        """The exact-case duplicate hits the UniqueValidator (which fires
        before validate_email): it must carry the friendly message, not
        DRF's default 'user with this email already exists.'"""
        response = self.client.post(
            self.register_url,
            {
                'full_name': 'Duplicate User',
                'email': 'existing@example.com',
                'profession': 'Student',
                'password': 'Orange!Mountain#5831',
                'confirm_password': 'Orange!Mountain#5831',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['email'][0],
            'A user with this email already exists.',
        )

    def test_registration_rejects_password_mismatch(self):
        response = self.client.post(
            self.register_url,
            {
                'full_name': 'Mismatch User',
                'email': 'mismatch@example.com',
                'profession': 'Student',
                'password': 'Orange!Mountain#5831',
                'confirm_password': 'Different!Password#9274',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_user_can_login_successfully(self):
        response = self.client.post(
            self.login_url,
            {
                'email': 'existing@example.com',
                'password': 'Violet!River#4829',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_login_is_case_insensitive_for_email(self):
        response = self.client.post(
            self.login_url,
            {
                'email': 'EXISTING@EXAMPLE.COM',
                'password': 'Violet!River#4829',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)

    def test_login_rejects_wrong_password(self):
        response = self.client.post(
            self.login_url,
            {
                'email': 'existing@example.com',
                'password': 'Wrong!Password#1234',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)


class TokenRefreshAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.refresh_url = '/api/v1/auth/token/refresh/'

        self.user = User.objects.create_user(
            email='refresh@example.com',
            full_name='Refresh Test User',
            profession='Student',
            password='SecureRefresh!4829',
        )

        self.refresh_token = str(RefreshToken.for_user(self.user))

    def test_valid_refresh_token_returns_new_tokens(self):
        response = self.client.post(
            self.refresh_url,
            {'refresh': self.refresh_token},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_old_refresh_token_cannot_be_reused_after_rotation(self):
        first_response = self.client.post(
            self.refresh_url,
            {'refresh': self.refresh_token},
            format='json',
        )

        self.assertEqual(first_response.status_code, 200)

        second_response = self.client.post(
            self.refresh_url,
            {'refresh': self.refresh_token},
            format='json',
        )

        self.assertEqual(second_response.status_code, 401)

    def test_new_refresh_token_can_be_used(self):
        first_response = self.client.post(
            self.refresh_url,
            {'refresh': self.refresh_token},
            format='json',
        )

        self.assertEqual(first_response.status_code, 200)

        new_refresh_token = first_response.data['refresh']

        second_response = self.client.post(
            self.refresh_url,
            {'refresh': new_refresh_token},
            format='json',
        )

        self.assertEqual(second_response.status_code, 200)
        self.assertIn('access', second_response.data)

    def test_invalid_refresh_token_is_rejected(self):
        response = self.client.post(
            self.refresh_url,
            {'refresh': 'invalid-refresh-token'},
            format='json',
        )

        self.assertEqual(response.status_code, 401)

    def test_missing_refresh_token_is_rejected(self):
        response = self.client.post(
            self.refresh_url,
            {},
            format='json',
        )

        self.assertEqual(response.status_code, 400)


class MeAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            email='me@example.com',
            full_name='Me Test User',
            profession='Student',
            password='SecureMe!4829',
        )

        self.refresh_token = RefreshToken.for_user(self.user)
        self.access_token = str(self.refresh_token.access_token)

        self.me_url = '/api/v1/auth/me/'

    def test_authenticated_user_can_retrieve_profile(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.access_token}'
        )

        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id', response.data)

    def test_profile_contains_correct_user_details(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.access_token}'
        )

        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.user.id)
        self.assertEqual(
            response.data['full_name'],
            'Me Test User',
        )
        self.assertEqual(
            response.data['email'],
            'me@example.com',
        )
        self.assertEqual(
            response.data['profession'],
            'Student',
        )

    def test_unauthenticated_user_cannot_access_profile(self):
        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, 401)

    def test_invalid_access_token_is_rejected(self):
        self.client.credentials(
            HTTP_AUTHORIZATION='Bearer invalid-access-token'
        )

        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, 401)


class UserDetailAPITests(TestCase):
    """GET /api/v1/auth/users/<id>/ — look up one user by ID (FIX 9)."""

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            email='detail.me@example.com',
            full_name='Detail Me',
            profession='Student',
        )
        self.other = User.objects.create_user(
            email='detail.other@example.com',
            full_name='Detail Other',
            profession='Doctor',
        )

        access = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

    def test_authenticated_user_can_look_up_another_user(self):
        response = self.client.get(f'/api/v1/auth/users/{self.other.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.other.id)
        self.assertEqual(response.data['full_name'], 'Detail Other')
        self.assertEqual(response.data['email'], 'detail.other@example.com')
        self.assertEqual(response.data['profession'], 'Doctor')

    def test_user_can_look_up_themselves(self):
        response = self.client.get(f'/api/v1/auth/users/{self.user.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.user.id)

    def test_unknown_user_returns_404(self):
        response = self.client.get('/api/v1/auth/users/999999/')

        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_user_cannot_look_up(self):
        self.client.credentials()  # clear auth
        response = self.client.get(f'/api/v1/auth/users/{self.other.id}/')

        self.assertEqual(response.status_code, 401)
