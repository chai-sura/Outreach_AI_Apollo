/**
 * Module: candidate_profile_extractor
 * Parses raw candidate inputs into a structured CandidateProfile via an LLM.
 *
 * Provider used here: Groq (OpenAI-compatible)
 * API key env: GROQ_API_KEY or pass groqApiKey as 2nd arg
 */

const EXTRACTION_PROMPT = `You are a precise resume parser. Extract a structured candidate profile from the provided inputs.

CRITICAL RULES:
- Only extract information explicitly present in the inputs. Do NOT infer or hallucinate credentials, employers, or skills not mentioned.
- If a field cannot be determined, set it to null or an empty array.
- You MUST extract at least 1 skill and 1 target_role for the pipeline to proceed.

Return ONLY valid JSON matching this exact schema (no markdown, no extra text):
{
  "candidate_id": "<uuid-v4>",
  "full_name": "<string | null>",
  "current_title": "<string | null>",
  "years_of_experience": <integer | null>,
  "skills": ["<string>"],
  "industries": ["<string>"],
  "past_companies": ["<string>"],
  "notable_projects": [
    {
      "title": "<string>",
      "description": "<string>",
      "impact": "<string | null>"
    }
  ],
  "education": {
    "degree": "<string | null>",
    "institution": "<string | null>",
    "field": "<string | null>"
  },
  "job_preferences": {
    "target_roles": ["<string>"],
    "target_industries": ["<string>"],
    "preferred_company_size": "<startup | mid_size | enterprise | any>",
    "location_preference": "<string | null>",
    "remote_preference": "<remote | hybrid | onsite | flexible | null>"
  },
  "extraction_confidence": "<high | medium | low>",
  "inferred_fields": ["<field names that were inferred rather than explicit>"]
}`;

function generateUUID() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    return (c === "x" ? r : (r & 0x3 | 0x8)).toString(16);
  });
}

function buildExtractionPrompt(inputs) {
  const { resume_text, linkedin_summary, portfolio_text, job_preferences } = inputs;

  let content = `RESUME:\n${resume_text}\n`;

  if (linkedin_summary) {
    content += `\nLINKEDIN SUMMARY:\n${linkedin_summary}\n`;
  }

  if (portfolio_text) {
    content += `\nPORTFOLIO / BIO:\n${portfolio_text}\n`;
  }

  if (job_preferences) {
    content += `\nJOB PREFERENCES PROVIDED BY CANDIDATE:\n`;
    if (job_preferences.target_roles?.length) {
      content += `Target Roles: ${job_preferences.target_roles.join(", ")}\n`;
    }
    if (job_preferences.target_industries?.length) {
      content += `Target Industries: ${job_preferences.target_industries.join(", ")}\n`;
    }
    if (job_preferences.preferred_company_size) {
      content += `Preferred Company Size: ${job_preferences.preferred_company_size}\n`;
    }
    if (job_preferences.location_preference) {
      content += `Location: ${job_preferences.location_preference}\n`;
    }
    if (job_preferences.remote_preference) {
      content += `Remote Preference: ${job_preferences.remote_preference}\n`;
    }
  }

  return `${EXTRACTION_PROMPT}\n\n${content}`;
}

function validateProfile(profile) {
  const errors = [];

  if (!profile.skills || profile.skills.length === 0) {
    errors.push("No skills extracted — pipeline cannot continue");
  }

  const targetRoles = profile.job_preferences?.target_roles;
  if (!targetRoles || targetRoles.length === 0) {
    errors.push("No target roles extracted — pipeline cannot continue");
  }

  return errors;
}

function truncateForTokenBudget(text, maxChars = 8000) {
  if (!text || text.length <= maxChars) return text;
  return text.slice(0, maxChars) + "\n[truncated for length]";
}

/**
 * @param {object} inputs
 * @param {string} inputs.resume_text
 * @param {string|null} inputs.linkedin_summary
 * @param {string|null} inputs.portfolio_text
 * @param {object|null} inputs.job_preferences
 * @param {string} [groqApiKey] - Groq API key (falls back to process.env.GROQ_API_KEY)
 * @returns {Promise<{ candidate_profile: object, module_status: string, warnings: string[] }>}
 */
async function runCandidateProfileExtractor(inputs, groqApiKey) {
  const warnings = [];
  const resolvedGroqApiKey = groqApiKey || process.env.GROQ_API_KEY;

  if (!inputs.resume_text || inputs.resume_text.trim().length < 100) {
    throw new Error("resume_text must be at least 100 characters");
  }

  if (!resolvedGroqApiKey) {
    throw new Error(
      "Missing Groq API key. Set GROQ_API_KEY in your environment or pass groqApiKey as an argument."
    );
  }

  const safeInputs = {
    ...inputs,
    resume_text: truncateForTokenBudget(inputs.resume_text, 8000),
    linkedin_summary: truncateForTokenBudget(inputs.linkedin_summary, 2000),
    portfolio_text: truncateForTokenBudget(inputs.portfolio_text, 2000),
  };

  const prompt = buildExtractionPrompt(safeInputs);

  let rawResponse;
  try {
    const response = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${resolvedGroqApiKey}`,
      },
      body: JSON.stringify({
        // Pick one supported Groq Llama-family model from the Groq model list.
        // Change this if you want another currently-supported model.
        model: "llama-3.3-70b-versatile",
        temperature: 0.1,
        max_tokens: 1500,

        // Groq supports JSON object mode on supported models.
        response_format: { type: "json_object" },

        messages: [
          {
            role: "user",
            content: prompt,
          },
        ],
      }),
    });

    if (!response.ok) {
      const errText = await response.text().catch(() => "");
      let errJson = {};
      try {
        errJson = JSON.parse(errText);
      } catch {
        // leave as empty object
      }

      throw new Error(
        errJson.error?.message || errText || `Groq API error: ${response.status}`
      );
    }

    const data = await response.json();
    rawResponse = data.choices?.[0]?.message?.content;

    if (!rawResponse) {
      throw new Error("Groq returned empty response");
    }
  } catch (e) {
    throw new Error(`candidate_profile_extractor LLM call failed: ${e.message}`);
  }

  let profile;
  try {
    const cleaned =
      typeof rawResponse === "string"
        ? rawResponse.replace(/```json|```/g, "").trim()
        : JSON.stringify(rawResponse);

    profile = JSON.parse(cleaned);
  } catch {
    throw new Error("candidate_profile_extractor: LLM returned malformed JSON — schema_violation");
  }

  if (!profile.candidate_id || String(profile.candidate_id).includes("<")) {
    profile.candidate_id = generateUUID();
  }

  profile.raw_resume_text = inputs.resume_text;

  const validationErrors = validateProfile(profile);
  if (validationErrors.length > 0) {
    profile.extraction_confidence = "low";
    warnings.push(...validationErrors);
    warnings.push("Profile extraction confidence is low — please review before proceeding");

    return {
      candidate_profile: profile,
      module_status: "fallback_used",
      warnings,
    };
  }

  if (profile.extraction_confidence === "low") {
    warnings.push("Some profile fields could not be confidently extracted and are marked as inferred");
  }

  return {
    candidate_profile: profile,
    module_status: "success",
    warnings,
  };
}

export { runCandidateProfileExtractor };