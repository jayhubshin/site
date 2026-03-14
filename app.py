def extract_base_address(address):
    # Updated regex pattern to correctly match addresses
    pattern = r'\d{1,5}\s[a-zA-Z\s]{2,}\s[a-zA-Z]{2,}\s[a-zA-Z]+\s\d{5}'
    match = re.search(pattern, address)
    if match:
        return match.group(0)
    return None

# Preventing SQL injection by using parameterized queries
query = "SELECT * FROM users WHERE username = %s AND password = %s"
# Execute the query with parameters
cursor.execute(query, (username, password))

# Completing truncated lines
result = cursor.fetchall()
return result
