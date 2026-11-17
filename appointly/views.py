"""Public pages for the Appointly backend.

These pages need no login: the homepage is the public landing page for the
project, and the privacy policy is linked from the Google OAuth consent
screen (required to publish the app out of Testing mode).
"""

from django.http import HttpResponse

_STYLE = """
body { font-family: system-ui, -apple-system, sans-serif; max-width: 720px;
       margin: 48px auto; padding: 0 20px; color: #1a1a1a; line-height: 1.6; }
h1 { font-size: 2rem; margin-bottom: 0.25em; }
h2 { margin-top: 1.5em; }
a { color: #1565c0; }
.muted { color: #666; font-size: 0.9em; }
"""

_HOMEPAGE_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Appointly</title>
<style>{_STYLE}</style></head>
<body>
<h1>Appointly</h1>
<p>Book appointments, chat, and make video calls &mdash; all in one app.</p>
<p>Appointly is a student project by Wasif Ali (Air University, Kamra Campus).
This server hosts the Appointly API used by the Flutter app.</p>
<ul>
  <li><a href="/privacy/">Privacy Policy</a></li>
  <li><a href="/admin/">Admin</a></li>
</ul>
<p class="muted">API base: <code>/api/v1/</code> &middot; Contact:
<a href="mailto:bestwasifali@gmail.com">bestwasifali@gmail.com</a></p>
</body>
</html>
"""

_PRIVACY_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Appointly &mdash; Privacy Policy</title>
<style>{_STYLE}</style></head>
<body>
<h1>Appointly Privacy Policy</h1>
<p class="muted">Last updated: 17 November 2026</p>
<p>Appointly is a student project by Wasif Ali (Air University, Kamra Campus).
This policy explains what data the Appointly app collects and how it is used.</p>

<h2>Data we collect</h2>
<ul>
  <li><strong>Account information:</strong> your full name, email address, and
  profession, provided when you register or sign in with Google.</li>
  <li><strong>Appointments:</strong> appointment details you create or accept,
  including dates, times, and notes.</li>
  <li><strong>Chat:</strong> messages, photos, and files you send in chats.</li>
  <li><strong>Calls:</strong> call records (who called whom, when, and for how
  long). Call audio and video are peer-to-peer and are not recorded or stored
  by us.</li>
</ul>

<h2>How we use it</h2>
<p>Your data is used only to provide the Appointly service: signing you in,
showing your appointments and chats, and connecting your calls. We do not sell
your personal data and do not share it with advertisers.</p>

<h2>Where it is stored</h2>
<p>Data is hosted with our service providers: Render (application hosting),
Neon (PostgreSQL database), MongoDB Atlas (chat data), and Cloudinary (chat
photos and files). Google Sign-In is used only to verify your identity when
you choose that sign-in method.</p>

<h2>Your choices</h2>
<p>You can ask for your account and data to be deleted at any time by emailing
<a href="mailto:bestwasifali@gmail.com">bestwasifali@gmail.com</a>.</p>

<h2>Contact</h2>
<p>Questions about this policy: Wasif Ali,
<a href="mailto:bestwasifali@gmail.com">bestwasifali@gmail.com</a>.</p>
</body>
</html>
"""


def homepage(request):
    """Public landing page at /."""
    return HttpResponse(_HOMEPAGE_HTML, content_type="text/html")


def privacy_policy(request):
    """Public privacy policy at /privacy/."""
    return HttpResponse(_PRIVACY_HTML, content_type="text/html")
