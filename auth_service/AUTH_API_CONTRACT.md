# Appointly — Authentication Service API Contract

**Base URL (Development):** `http://localhost:8000`

**API Prefix:** `/api/v1/auth/`

All request and response bodies use JSON unless stated otherwise.

---

## 1. JWT Configuration

| Setting | Value |
|---|---|
| Access token lifetime | 15 minutes |
| Refresh token lifetime | 7 days |
| Refresh token rotation | Enabled |
| Blacklisting after rotation | Enabled |
| Authorization header | `Bearer <access_token>` |

## 2. User Object

All endpoints returning user information use this structure:

```json
{
  "id": 1,
  "full_name": "Jane Doe",
  "email": "jane@example.com",
  "profession": "Dentist"
}
```

| Field | Type | Description |
|---|---|---|
| id | integer | Unique user ID |
| full_name | string | User's full name |
| email | string | Unique email address |
| profession | string | User's profession |

---

# 3. API Endpoints

## 3.1 Register

Create a new Appointly account.

- **Method:** POST
- **URL:** `/api/v1/auth/register/`
- **Authentication:** Not required

### Request body

```json
{
  "full_name": "Jane Doe",
  "email": "jane@example.com",
  "profession": "Dentist",
  "password": "SecurePass123!",
  "confirm_password": "SecurePass123!"
}
```

All fields are required.

| Field | Type | Notes |
|---|---|---|
| full_name | string | Maximum 150 characters |
| email | string | Must be unique; case-insensitive |
| profession | string | Maximum 100 characters |
| password | string | Must satisfy Django password validators |
| confirm_password | string | Must match password |

### Success — 201 Created

```json
{
  "message": "User registered successfully.",
  "user": {
    "id": 1,
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "profession": "Dentist"
  }
}
```

### Common errors

- `400 Bad Request`: Missing or invalid fields.
- `400 Bad Request`: Password confirmation mismatch.
- `400 Bad Request`: Duplicate email.
- `400 Bad Request`: Password does not satisfy configured validators.

---

## 3.2 Login

Authenticate using email and password.

- **Method:** POST
- **URL:** `/api/v1/auth/login/`
- **Authentication:** Not required

### Request body

```json
{
  "email": "jane@example.com",
  "password": "SecurePass123!"
}
```

Both fields are required.

Email comparison is case-insensitive.

### Success — 200 OK

```json
{
  "message": "Login successful.",
  "user": {
    "id": 1,
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "profession": "Dentist"
  },
  "tokens": {
    "access": "<access_token>",
    "refresh": "<refresh_token>"
  }
}
```

### Error

`400 Bad Request` — Invalid email, incorrect password, or inactive account.

```json
{
  "detail": "Invalid email or password."
}
```

The same error is used for these cases to avoid revealing whether an account exists.

---

## 3.3 Google Sign-In

Authenticate or register a user through Google Sign-In.

- **Method:** POST
- **URL:** `/api/v1/auth/google/`
- **Authentication:** Not required

The Flutter client obtains a Google ID token through the Google Sign-In SDK and sends it to this endpoint.

### Request body

```json
{
  "id_token": "<google_id_token>",
  "profession": "Student"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| id_token | string | Yes | Google ID token from client SDK |
| profession | string | Conditional | Required for a new Appointly user; maximum 100 characters |

### Success — 200 OK

```json
{
  "message": "Google Sign-In successful.",
  "user": {
    "id": 1,
    "full_name": "Jane Doe",
    "email": "jane@gmail.com",
    "profession": "Student"
  },
  "tokens": {
    "access": "<access_token>",
    "refresh": "<refresh_token>"
  }
}
```

The same success structure is returned for existing Google-linked users and newly created users.

### Error responses

| Status | Meaning |
|---|---|
| 400 | Missing or invalid request fields |
| 400 | Profession required for a new user |
| 401 | Google ID token invalid or verification failed |
| 403 | Existing Google account is inactive |
| 409 | Email already belongs to an account that is not linked to Google |
| 409 | Concurrent account creation conflict |

**Important behavior:**

- Google ID tokens are verified by the backend.
- Google accounts are identified using Google's unique subject ID (`google_id`).
- Existing accounts are not automatically linked by matching email.
- A new Google account requires a profession.
- If Google does not provide a name, the email's local part is used as a fallback.
- New Google users receive an unusable password and must use Google Sign-In.

---

## 3.4 Logout

Blacklist the authenticated user's refresh token.

- **Method:** POST
- **URL:** `/api/v1/auth/logout/`
- **Authentication:** Required — Access token

### Request headers

```http
Content-Type: application/json
Authorization: Bearer <access_token>
```

### Request body

```json
{
  "refresh": "<refresh_token>"
}
```

### Success — 205 Reset Content

```json
{
  "message": "Logout successful."
}
```

### Error responses

| Status | Meaning |
|---|---|
| 400 | Missing refresh token |
| 400 | Invalid, expired, or unusable refresh token |
| 401 | Missing or invalid access token |
| 403 | Refresh token belongs to another user |

The backend verifies that the refresh token belongs to the authenticated user before blacklisting it.

---

## 3.5 Current User Profile (Me)

Retrieve the currently authenticated user's profile.

- **Method:** GET
- **URL:** `/api/v1/auth/me/`
- **Authentication:** Required — Access token

### Request headers

```http
Authorization: Bearer <access_token>
```

No request body is required.

### Success — 200 OK

```json
{
  "user": {
    "id": 1,
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "profession": "Dentist"
  }
}
```

### Error responses

- `401 Unauthorized`: Missing, invalid, or expired access token.

---

## 3.6 Token Refresh

Exchange a valid refresh token for a new access/refresh token pair.

- **Method:** POST
- **URL:** `/api/v1/auth/token/refresh/`
- **Authentication:** Refresh token required in request body

### Request body

```json
{
  "refresh": "<refresh_token>"
}
```

### Success — 200 OK

```json
{
  "access": "<new_access_token>",
  "refresh": "<new_refresh_token>"
}
```

Because rotation is enabled, the old refresh token is blacklisted after successful refresh.

### Error responses

- `400 Bad Request`: Missing refresh token.
- `401 Unauthorized`: Invalid, expired, or blacklisted refresh token.

---

# 4. Integration Rules for Flutter

## 4.1 Secure token storage

Store both tokens securely using a secure storage solution such as `flutter_secure_storage`.

Do not store authentication tokens in ordinary preferences or expose them in logs.

## 4.2 Protected requests

For protected endpoints, send the access token:

```http
Authorization: Bearer <access_token>
```

Never send the refresh token as the Authorization header.

## 4.3 Refresh workflow

When the access token expires:

1. Send the stored refresh token to `/api/v1/auth/token/refresh/`.
2. Receive the new access and refresh tokens.
3. Replace both stored tokens.
4. Never reuse the previous refresh token.

## 4.4 Logout workflow

1. Send the access token in the Authorization header.
2. Send the refresh token in the request body.
3. After successful logout, delete both stored tokens.
4. Navigate the user to the login screen.

## 4.5 User identity across services

The authenticated user's `id` is the unique Appointly user identifier.

The JWT includes this identity in its `user_id` claim under the current SimpleJWT configuration.

Other services should use this ID to associate appointments, chats, notifications, tasks, and profiles with the correct user.

---

# 5. Endpoint Summary

| Method | Endpoint | Authentication | Purpose |
|---|---|---|---|
| POST | `/api/v1/auth/register/` | None | Create account |
| POST | `/api/v1/auth/login/` | None | Email/password login |
| POST | `/api/v1/auth/google/` | None | Google Sign-In |
| POST | `/api/v1/auth/logout/` | Access token | Revoke refresh token |
| GET | `/api/v1/auth/me/` | Access token | Get current user |
| POST | `/api/v1/auth/token/refresh/` | Refresh token in body | Rotate tokens |

---

**Development note:** The URLs above use localhost. When another device or teammate accesses the backend, replace `localhost` with the backend server's reachable IP address or configured hostname.
