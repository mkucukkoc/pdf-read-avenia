from schemas import SocialPostRequest
from endpoints.social_posts import run_social_posts
from endpoints.agent.baseAgent import handler_agent

social_posts_agent = handler_agent(
    name="social_posts_agent",
    description="Hazır sosyal medya postları yazar, konuya uygun emoji ve hashtag ekler.",
    request_model=SocialPostRequest,
    handler=run_social_posts,
)


