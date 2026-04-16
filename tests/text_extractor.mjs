console.log("GROQ_API_KEY in Node:", process.env.GROQ_API_KEY ? "SET" : "MISSING");

import { runCandidateProfileExtractor } from "../modules/candidate_profile_extractor.js";
// If you kept the old filename, use this instead:
// import { runCandidateProfileExtractor } from "../modules/OLD_candidate_profile_extractor.js";

const inputs = {
  resume_text: `
Jane Doe is a Software Engineer with 4 years of experience building React and Node.js applications.
She worked at Acme Corp and BrightLabs, built an internal analytics dashboard, and improved report generation speed by 40%.
Skills include JavaScript, React, Node.js, SQL, and REST APIs.
She is targeting Backend Engineer and Full Stack Engineer roles in SaaS companies, prefers remote work.
`.repeat(2), // ensures >100 chars
  linkedin_summary: null,
  portfolio_text: null,
  job_preferences: {
    target_roles: ["Backend Engineer", "Full Stack Engineer"],
    target_industries: ["SaaS"],
    preferred_company_size: "mid_size",
    location_preference: "Remote",
    remote_preference: "remote",
  },
};

try {
  // Uses process.env.GROQ_API_KEY automatically
  const result = await runCandidateProfileExtractor(inputs);

  // Or pass explicitly:
  // const result = await runCandidateProfileExtractor(inputs, process.env.GROQ_API_KEY);

  console.log(JSON.stringify(result, null, 2));
} catch (err) {
  console.error("TEST FAILED:", err.message);
  process.exit(1);
}