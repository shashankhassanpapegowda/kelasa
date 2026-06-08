# Auth Testing Playbook (Emergent Google Auth)

Step 1: Create Test User & Session
```
mongosh --eval "
use('test_database');
var userId = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({
  user_id: userId,
  email: 'test.user.' + Date.now() + '@example.com',
  name: 'Test User',
  picture: 'https://via.placeholder.com/150',
  role: 'admin',
  created_at: new Date()
});
db.user_sessions.insertOne({
  user_id: userId,
  session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000),
  created_at: new Date()
});
print('Session token: ' + sessionToken);
print('User ID: ' + userId);
"
```

Step 2: Test Backend API
```
curl -X GET "$BASE_URL/api/auth/me" -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

Step 3: Browser Testing - set cookie session_token and navigate to /

Checklist:
- user_id custom UUID field
- session.user_id matches user.user_id
- Projections exclude _id
- /api/auth/me returns user data
