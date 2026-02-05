from src.logistics_agent import LogisticsAgent

a = LogisticsAgent()
q = 'What is 2+2?'
r = a.invoke(q, thread_id='test')
print(r['messages'][-1].content)
