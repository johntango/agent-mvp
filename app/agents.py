from agents import Agent, Runner

def make_architect_agent():
    return Agent(name='Architect', instructions='Design', output_type=None)

def make_implementer_agent():
    return Agent(name='Implementer', instructions='Implement', output_type=None)

def make_tester_agent():
    return Agent(name='Tester', instructions='Test', output_type=None)

def make_reviewer_agent():
    return Agent(name='Reviewer', instructions='Review', output_type=None)
