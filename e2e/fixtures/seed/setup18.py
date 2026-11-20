import datetime
from django.utils import timezone
from core.models import User
from chat.models import Conversation, Participant, Message
a=User.objects.get(username='zz_e307_fac5'); b=User.objects.get(username='zz_e307_ger5')
lo,hi=sorted([str(a.pk),str(b.pk)])
key=f'{lo}:{hi}'
conv,c=Conversation.objects.get_or_create(direct_key=key,defaults=dict(kind='DIRECT'))
for u in (a,b): Participant.objects.get_or_create(conversation=conv,user=u)
if c or Message.objects.filter(conversation=conv).count()<35:
    Message.objects.filter(conversation=conv).delete()
    base=timezone.now()-datetime.timedelta(minutes=60)
    for i in range(1,36):
        m=Message.objects.create(conversation=conv,sender=a if i%2 else b,body=f'SEED-{i:02d}')
        Message.objects.filter(pk=m.pk).update(created_at=base+datetime.timedelta(minutes=i))
    Conversation.objects.filter(pk=conv.pk).update(last_message_at=base+datetime.timedelta(minutes=35))
print(c, Message.objects.filter(conversation=conv).count())
