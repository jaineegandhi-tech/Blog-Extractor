import httpx
resp = httpx.get('https://www.esparkinfo.com/blog/', follow_redirects=True)
print('Status:', resp.status_code)
print('Pagination in HTML:', 'page' in resp.text.lower())
print('URLs with /blog/:', [line for line in resp.text.split('"') if '/blog/' in line][:10])
