"""Tests for the public homepage and privacy policy pages."""

from django.test import TestCase


class PublicPagesTests(TestCase):
    def test_homepage_is_public(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Appointly")
        self.assertContains(response, "/privacy/")

    def test_privacy_policy_is_public(self):
        response = self.client.get("/privacy/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Privacy Policy")
        self.assertContains(response, "bestwasifali@gmail.com")
