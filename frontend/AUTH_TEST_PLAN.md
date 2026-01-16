# Authentication Flow Test Plan

This document outlines comprehensive test cases for the authentication and session management system, with special focus on preventing redirect loops.

## Test Environment Setup

Before testing, ensure:
1. Backend is running (`./scripts/dev-up.sh`)
2. Frontend is accessible at `http://localhost:3000`
3. Session storage and local storage are cleared
4. You have valid test credentials (admin@example.com / changeme)

## Critical Anti-Loop Measures

The following mechanisms prevent redirect loops:

1. **Return URL Storage**: Uses sessionStorage (not URL params) to prevent infinite redirect chains
2. **Redirect Flags**: `isRedirecting` ref tracks ongoing redirects
3. **Path Checks**: Never redirects to `/login` from `/login`
4. **Loading State**: Waits for auth check to complete before redirecting
5. **One-Time Redirect**: `hasRedirected` ref prevents multiple redirect attempts

## Test Cases

### Category 1: Login Page Behavior

#### Test 1.1: Clean Login Page (No Navigation)
**Objective**: Verify login page has no navigation/sidebars

**Steps**:
1. Clear all storage (localStorage + sessionStorage)
2. Navigate to `http://localhost:3000/login`
3. Observe the page layout

**Expected**:
- ✓ Login form is visible
- ✓ No top navigation bar
- ✓ No left sidebar
- ✓ No status bar at bottom
- ✓ Only the login form and credentials hint

**Status**: ☐ Pass ☐ Fail

---

#### Test 1.2: Successful Login Redirect
**Objective**: User is redirected to home after successful login

**Steps**:
1. Navigate to `http://localhost:3000/login`
2. Enter valid credentials (admin@example.com / changeme)
3. Click "Sign in"

**Expected**:
- ✓ Login succeeds without errors
- ✓ Redirect to `http://localhost:3000/` (home)
- ✓ Navigation/sidebar becomes visible
- ✓ User info shown in navigation

**Status**: ☐ Pass ☐ Fail

---

#### Test 1.3: Already Authenticated Redirect
**Objective**: Authenticated users cannot access login page

**Steps**:
1. Login successfully (see Test 1.2)
2. Manually navigate to `http://localhost:3000/login`

**Expected**:
- ✓ Immediately redirected to home page
- ✓ No flash of login form
- ✓ URL changes to `http://localhost:3000/`

**Status**: ☐ Pass ☐ Fail

---

### Category 2: Protected Routes

#### Test 2.1: Unauthenticated Access Blocked
**Objective**: Unauthenticated users cannot access protected pages

**Steps**:
1. Clear all storage (logout)
2. Navigate to `http://localhost:3000/connections`

**Expected**:
- ✓ Redirect to `/login`
- ✓ URL becomes `http://localhost:3000/login`
- ✓ Return URL stored in sessionStorage: `/connections`
- ✓ Login form displayed

**Status**: ☐ Pass ☐ Fail

---

#### Test 2.2: Return to Intended Page After Login
**Objective**: After login, user returns to originally requested page

**Steps**:
1. Clear all storage (logout)
2. Navigate to `http://localhost:3000/connections`
3. Should redirect to login (see Test 2.1)
4. Enter valid credentials and login

**Expected**:
- ✓ After login, redirect to `/connections` (not home)
- ✓ Connections page loads with navigation
- ✓ sessionStorage return URL is cleared

**Status**: ☐ Pass ☐ Fail

---

#### Test 2.3: Multiple Protected Page Attempts
**Objective**: Verify return URL is updated for each new page attempt

**Steps**:
1. Logout completely
2. Navigate to `http://localhost:3000/settings`
3. Verify redirect to login
4. DON'T login yet - navigate to `http://localhost:3000/connections`
5. Now login

**Expected**:
- ✓ After login, redirect to `/connections` (last attempted page)
- ✓ Not redirected to `/settings` (first attempt)

**Status**: ☐ Pass ☐ Fail

---

### Category 3: Session Expiration

#### Test 3.1: Token Expiration Handling
**Objective**: Expired tokens trigger logout and redirect

**Steps**:
1. Login successfully
2. Navigate to any protected page
3. In browser DevTools console, run:
   ```javascript
   localStorage.setItem('curatore_access_token', 'invalid_token')
   ```
4. Refresh the page

**Expected**:
- ✓ Invalid token detected
- ✓ Redirect to `/login`
- ✓ Current page stored as return URL
- ✓ Error logged to console
- ✓ Tokens cleared from storage

**Status**: ☐ Pass ☐ Fail

---

#### Test 3.2: Session Expiration During Use
**Objective**: Handle session expiration while user is active

**Steps**:
1. Login successfully
2. Navigate to `/documents`
3. Manually clear tokens:
   ```javascript
   localStorage.removeItem('curatore_access_token')
   localStorage.removeItem('curatore_refresh_token')
   ```
4. Try to navigate to another page (e.g., click "Connections")

**Expected**:
- ✓ Redirect to `/login`
- ✓ Return URL set to intended destination
- ✓ No infinite redirects
- ✓ User can login and continue

**Status**: ☐ Pass ☐ Fail

---

### Category 4: Redirect Loop Prevention

#### Test 4.1: No Loop on Repeated Login Attempts
**Objective**: Failed login doesn't cause redirect loops

**Steps**:
1. Logout completely
2. Navigate to `/login`
3. Enter WRONG credentials
4. Click "Sign in"
5. Observe behavior

**Expected**:
- ✓ Error message displayed
- ✓ Stays on `/login` page
- ✓ No redirect loops
- ✓ Can retry login

**Status**: ☐ Pass ☐ Fail

---

#### Test 4.2: No Loop from Login to Login
**Objective**: Prevent redirect when login redirects to itself

**Steps**:
1. In browser console, set:
   ```javascript
   sessionStorage.setItem('auth_return_url', '/login')
   ```
2. Navigate to `/login`
3. Login with valid credentials

**Expected**:
- ✓ After login, redirect to `/` (home), NOT `/login`
- ✓ Return URL sanitized
- ✓ No infinite loop

**Status**: ☐ Pass ☐ Fail

---

#### Test 4.3: Browser Back Button Behavior
**Objective**: Back button doesn't cause redirect loops

**Steps**:
1. Login successfully
2. Navigate to `/connections`
3. Click browser back button

**Expected**:
- ✓ Returns to previous page (home)
- ✓ No redirect to login
- ✓ Still authenticated
- ✓ Navigation still visible

**Status**: ☐ Pass ☐ Fail

---

### Category 5: Logout Behavior

#### Test 5.1: Manual Logout
**Objective**: Logout clears state and redirects properly

**Steps**:
1. Login successfully
2. Navigate to any page (e.g., `/documents`)
3. Click logout button in navigation

**Expected**:
- ✓ Redirect to `/login`
- ✓ Tokens cleared from localStorage
- ✓ Return URL stored (should be `/documents`)
- ✓ Navigation/sidebar hidden

**Status**: ☐ Pass ☐ Fail

---

#### Test 5.2: Logout with Return URL
**Objective**: After logout and re-login, return to previous page

**Steps**:
1. Login successfully
2. Navigate to `/connections`
3. Logout from navigation
4. Login again with same credentials

**Expected**:
- ✓ After logout, redirect to `/login`
- ✓ After re-login, redirect to `/connections`
- ✓ Connections page loads normally

**Status**: ☐ Pass ☐ Fail

---

### Category 6: Page Refresh Scenarios

#### Test 6.1: Refresh While Authenticated
**Objective**: Page refresh maintains authentication

**Steps**:
1. Login successfully
2. Navigate to `/documents`
3. Press F5 (refresh)

**Expected**:
- ✓ Page reloads
- ✓ Still authenticated
- ✓ Navigation still visible
- ✓ No redirect to login
- ✓ Tokens still in localStorage

**Status**: ☐ Pass ☐ Fail

---

#### Test 6.2: Refresh on Login Page
**Objective**: Login page refresh doesn't cause loops

**Steps**:
1. Navigate to `/login` (not logged in)
2. Press F5 multiple times

**Expected**:
- ✓ Page refreshes normally
- ✓ Stays on `/login`
- ✓ No redirect loops
- ✓ Login form still accessible

**Status**: ☐ Pass ☐ Fail

---

#### Test 6.3: Refresh After Logout
**Objective**: Refresh after logout maintains logged-out state

**Steps**:
1. Login successfully
2. Logout
3. Press F5 (refresh)

**Expected**:
- ✓ Stays on `/login`
- ✓ No automatic re-authentication
- ✓ Tokens still cleared
- ✓ Must login again

**Status**: ☐ Pass ☐ Fail

---

### Category 7: Edge Cases

#### Test 7.1: Direct URL Access
**Objective**: Deep links work correctly

**Steps**:
1. Logout completely
2. Paste `http://localhost:3000/connections` directly in URL bar
3. Press Enter

**Expected**:
- ✓ Redirect to `/login`
- ✓ Return URL stored: `/connections`
- ✓ After login, redirect to `/connections`

**Status**: ☐ Pass ☐ Fail

---

#### Test 7.2: Multiple Browser Tabs
**Objective**: Logout in one tab affects others

**Steps**:
1. Login successfully
2. Open two tabs: Tab A on `/documents`, Tab B on `/connections`
3. In Tab A, logout
4. Switch to Tab B and try to interact

**Expected**:
- ✓ Tab A redirects to `/login`
- ✓ Tab B may show stale content initially
- ✓ Tab B redirects to `/login` on next interaction/refresh
- ✓ No errors or loops

**Status**: ☐ Pass ☐ Fail

---

#### Test 7.3: Network Error During Auth Check
**Objective**: Handle network failures gracefully

**Steps**:
1. Login successfully
2. In browser DevTools, enable "Offline" mode
3. Refresh the page

**Expected**:
- ✓ Shows error state or loading indefinitely
- ✓ No redirect loops
- ✓ When back online, auth check completes
- ✓ User can continue or re-login

**Status**: ☐ Pass ☐ Fail

---

## Testing Checklist

Before marking complete, verify:

- [ ] All 20 test cases executed
- [ ] No redirect loops observed in any scenario
- [ ] Console shows no React warnings/errors
- [ ] Network tab shows no repeated requests
- [ ] sessionStorage properly managed (return URLs)
- [ ] localStorage properly managed (tokens)
- [ ] Navigation visibility toggled correctly
- [ ] User experience is smooth (no flashing)

## Known Issues

Document any issues found during testing:

1. Issue: _____
   - Test Case: _____
   - Severity: High/Medium/Low
   - Reproduction: _____

## Sign-off

- Tester: _____________________
- Date: _____________________
- Environment: Development / Staging / Production
- Result: ☐ All tests passed ☐ Issues found (see above)
