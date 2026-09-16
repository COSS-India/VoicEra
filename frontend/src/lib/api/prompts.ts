import { apiFetch } from "@/lib/api/http";

interface RefinePromptRequest {
  prompt: string;
  llmProvider: string;
  llmModel: string;
}

interface RefinePromptResponse {
  refined_prompt: string;
}

/** Rewrites a draft system prompt for voice delivery via the agent's own
 * configured LLM provider/model — see apps/api/app/routers/prompt_refine.py. */
export async function refinePrompt(input: RefinePromptRequest): Promise<string> {
  const { refined_prompt } = await apiFetch<RefinePromptResponse>("/prompts/refine", {
    method: "POST",
    body: JSON.stringify({
      prompt: input.prompt,
      llm_provider: input.llmProvider,
      llm_model: input.llmModel,
    }),
  });
  return refined_prompt;
}
