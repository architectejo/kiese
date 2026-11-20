from clients.models import Client
n=0
for c in Client.objects.filter(notes__startswith='ZZ e2e')|Client.objects.filter(first_name='ZZE301'):
    c.refresh_category(); c.save(update_fields=['category']); n+=1
print(n, list(Client.objects.filter(code__in=['K1-0079','K1-0081','K1-0085']).values_list('code','category')))
