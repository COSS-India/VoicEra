import { describe, expect, it } from "vitest";
import { messageToPlainText } from "@/components/call/CallStage";
import type { ConversationMessagePart } from "@pipecat-ai/client-react";

function stringPart(text: string, needsSeparator = false): ConversationMessagePart {
  return {
    text,
    needsSeparator,
    final: true,
    createdAt: new Date().toISOString(),
  } as ConversationMessagePart;
}

function botOutputPart(
  spoken: string,
  unspoken: string | undefined,
  needsSeparator = false,
): ConversationMessagePart {
  return {
    text: { spoken, unspoken },
    needsSeparator,
    final: true,
    createdAt: new Date().toISOString(),
  } as ConversationMessagePart;
}

describe("messageToPlainText", () => {
  it("returns an empty string for no parts", () => {
    expect(messageToPlainText([])).toBe("");
  });

  it("concatenates plain string parts", () => {
    expect(messageToPlainText([stringPart("Hello"), stringPart(" world")])).toBe("Hello world");
  });

  it("inserts a separator only when needsSeparator is set", () => {
    const parts = [stringPart("Hello"), stringPart("world", true)];
    expect(messageToPlainText(parts)).toBe("Hello world");
  });

  it("flattens bot output text to spoken + unspoken, ignoring the spoken/unspoken UI split", () => {
    expect(messageToPlainText([botOutputPart("Hi there", ", how can I help?")])).toBe(
      "Hi there, how can I help?",
    );
  });

  it("treats a missing unspoken field as empty", () => {
    expect(messageToPlainText([botOutputPart("Hi", undefined)])).toBe("Hi");
  });

  it("mixes string and bot-output parts in order", () => {
    const parts = [stringPart("User said hi. "), botOutputPart("Hello", "!")];
    expect(messageToPlainText(parts)).toBe("User said hi. Hello!");
  });
});
