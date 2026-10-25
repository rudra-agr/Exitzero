import urllib.request

# Bug: wrong URL / connection refused
response = urllib.request.urlopen("http://localhost:9999/api/data", timeout=2)
print(response.read())
