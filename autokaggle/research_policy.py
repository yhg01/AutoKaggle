"""Explicit public-answer research policy; private-answer evaluation stays default."""
PUBLIC_MODE = 'public_research'
DISCLOSURE = ('Public-data research: test answers are available outside this service. '
              'This is not a blind evaluation. Prior model knowledge or earlier access can affect the score. '
              'A code review or successful reproduction does not remove these limits.')
ACCESS_RULES = ('Use only the supplied training data, approved references, and declared dependencies. '
                'Do not search for test answers, embed test-label lookup tables, probe scorer files or credentials, '
                'or use unauthorized network services. Only the published submission endpoint is permitted for scoring. '
                'A downloaded package cannot enforce access restrictions on your machine. '
                'Keep an execution record and disclose earlier access to the answers.')


def is_public(project):
    return project.get('answers', {}).get('research_mode', 'private') == PUBLIC_MODE
