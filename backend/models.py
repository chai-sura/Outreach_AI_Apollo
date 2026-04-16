from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class OnboardRequest(BaseModel):
    name: str
    email: str
    goal: str


class OnboardResponse(BaseModel):
    profile_id: str
    status: str


class SearchRequest(BaseModel):
    user_query: str
    profile_id: str


class SearchResponse(BaseModel):
    contacts: List[Dict[str, Any]]
    count: int


class EnrichRequest(BaseModel):
    contact: Dict[str, Any]
    profile_id: str


class EnrichResponse(BaseModel):
    enriched_contact: Dict[str, Any]


class RunPipelineRequest(BaseModel):
    user_query: str
    profile_id: str


class RunPipelineResponse(BaseModel):
    results: List[Dict[str, Any]]
    count: int


class SendEmailRequest(BaseModel):
    contact_email: str
    contact_name: str
    subject: str
    body: str
    profile_id: str


class SendEmailResponse(BaseModel):
    status: str
    email_id: str
    timestamp: str


class DashboardResponse(BaseModel):
    summary: Dict[str, Any]
    emails: List[Dict[str, Any]]


class Contact(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    linkedin_url: Optional[str] = None
    company_id: Optional[str] = None
    funding_stage: Optional[str] = None
    headcount: Optional[str] = None
    technologies: Optional[List[str]] = []
    industry: Optional[str] = None
    seniority: Optional[str] = None


class AgentResult(BaseModel):
    contact: Dict[str, Any]
    match_score: int = 0
    email_score: int = 0
    strategy: str = ""
    subject: str = ""
    body: str = ""
    news: str = ""
    status: str = "pending"
