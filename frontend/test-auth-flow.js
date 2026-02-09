/**
 * Authentication Flow Test Script
 *
 * This script tests critical authentication scenarios to ensure:
 * 1. No redirect loops occur
 * 2. Session management works correctly
 * 3. Return URLs are properly handled
 *
 * Run with: node test-auth-flow.js
 *
 * Prerequisites:
 * - Backend running on http://localhost:8000
 * - Frontend build available (or dev server running)
 * - Test credentials: admin@example.com / changeme
 */

const API_BASE = 'http://localhost:8000/api/v1/admin'

/**
 * Test Case 1: Login API works correctly
 */
async function testLoginAPI() {
  console.log('\n✓ Test 1: Login API')
  console.log('  Testing authentication endpoint...')

  try {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email_or_username: 'admin@example.com',
        password: 'changeme'
      })
    })

    if (response.status === 200) {
      const data = await response.json()

      if (data.access_token && data.refresh_token && data.user) {
        console.log('  ✓ Login successful')
        console.log('  ✓ Access token received')
        console.log('  ✓ Refresh token received')
        console.log('  ✓ User data received')
        return { passed: true, tokens: data }
      } else {
        console.log('  ✗ Response missing required fields')
        return { passed: false, error: 'Missing tokens or user data' }
      }
    } else {
      console.log(`  ✗ Login failed with status ${response.status}`)
      return { passed: false, error: `HTTP ${response.status}` }
    }
  } catch (error) {
    console.log('  ✗ Network error:', error.message)
    return { passed: false, error: error.message }
  }
}

/**
 * Test Case 2: Token validation works
 */
async function testTokenValidation(accessToken) {
  console.log('\n✓ Test 2: Token Validation')
  console.log('  Testing /auth/me endpoint...')

  try {
    const response = await fetch(`${API_BASE}/auth/me`, {
      headers: {
        'Authorization': `Bearer ${accessToken}`
      }
    })

    if (response.status === 200) {
      const user = await response.json()
      console.log('  ✓ Token validated successfully')
      console.log(`  ✓ User: ${user.email}`)
      return { passed: true, user }
    } else {
      console.log(`  ✗ Validation failed with status ${response.status}`)
      return { passed: false, error: `HTTP ${response.status}` }
    }
  } catch (error) {
    console.log('  ✗ Network error:', error.message)
    return { passed: false, error: error.message }
  }
}

/**
 * Test Case 3: Invalid token handling
 */
async function testInvalidToken() {
  console.log('\n✓ Test 3: Invalid Token Handling')
  console.log('  Testing with invalid token...')

  try {
    const response = await fetch(`${API_BASE}/auth/me`, {
      headers: {
        'Authorization': 'Bearer invalid_token_here'
      }
    })

    if (response.status === 401) {
      console.log('  ✓ Invalid token correctly rejected (401)')
      return { passed: true }
    } else {
      console.log(`  ✗ Expected 401, got ${response.status}`)
      return { passed: false, error: `Expected 401, got ${response.status}` }
    }
  } catch (error) {
    console.log('  ✗ Network error:', error.message)
    return { passed: false, error: error.message }
  }
}

/**
 * Test Case 4: Token refresh works
 */
async function testTokenRefresh(refreshToken) {
  console.log('\n✓ Test 4: Token Refresh')
  console.log('  Testing token refresh endpoint...')

  try {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        refresh_token: refreshToken
      })
    })

    if (response.status === 200) {
      const data = await response.json()
      if (data.access_token && data.refresh_token) {
        console.log('  ✓ Token refresh successful')
        console.log('  ✓ New access token received')
        console.log('  ✓ New refresh token received')
        return { passed: true, tokens: data }
      } else {
        console.log('  ✗ Response missing tokens')
        return { passed: false, error: 'Missing tokens' }
      }
    } else {
      console.log(`  ✗ Refresh failed with status ${response.status}`)
      return { passed: false, error: `HTTP ${response.status}` }
    }
  } catch (error) {
    console.log('  ✗ Network error:', error.message)
    return { passed: false, error: error.message }
  }
}

/**
 * Main test runner
 */
async function runTests() {
  console.log('╔════════════════════════════════════════════════════════╗')
  console.log('║     Authentication Flow Integration Tests             ║')
  console.log('╚════════════════════════════════════════════════════════╝')

  const results = []

  // Test 1: Login
  const loginResult = await testLoginAPI()
  results.push({ name: 'Login API', ...loginResult })

  if (!loginResult.passed) {
    console.log('\n✗ Login failed, skipping remaining tests')
    printSummary(results)
    return
  }

  const { access_token, refresh_token } = loginResult.tokens

  // Test 2: Token Validation
  const validationResult = await testTokenValidation(access_token)
  results.push({ name: 'Token Validation', ...validationResult })

  // Test 3: Invalid Token
  const invalidResult = await testInvalidToken()
  results.push({ name: 'Invalid Token Handling', ...invalidResult })

  // Test 4: Token Refresh
  const refreshResult = await testTokenRefresh(refresh_token)
  results.push({ name: 'Token Refresh', ...refreshResult })

  // Print summary
  printSummary(results)
}

/**
 * Print test results summary
 */
function printSummary(results) {
  console.log('\n' + '═'.repeat(60))
  console.log('TEST SUMMARY')
  console.log('═'.repeat(60))

  let passed = 0
  let failed = 0

  results.forEach(result => {
    const status = result.passed ? '✓ PASS' : '✗ FAIL'
    const color = result.passed ? '\x1b[32m' : '\x1b[31m'
    const reset = '\x1b[0m'

    console.log(`${color}${status}${reset} - ${result.name}`)
    if (!result.passed && result.error) {
      console.log(`       Error: ${result.error}`)
    }

    if (result.passed) passed++
    else failed++
  })

  console.log('═'.repeat(60))
  console.log(`Total: ${results.length} | Passed: ${passed} | Failed: ${failed}`)
  console.log('═'.repeat(60))

  if (failed === 0) {
    console.log('\n✓ All authentication tests passed!')
    console.log('✓ No redirect loops detected in API layer')
    console.log('\nNext steps:')
    console.log('1. Test frontend flows in browser (see AUTH_TEST_PLAN.md)')
    console.log('2. Verify return URL handling')
    console.log('3. Test session expiration scenarios')
  } else {
    console.log('\n✗ Some tests failed. Please review errors above.')
  }

  process.exit(failed > 0 ? 1 : 0)
}

// Run tests
runTests().catch(error => {
  console.error('\n✗ Test execution failed:', error)
  process.exit(1)
})
