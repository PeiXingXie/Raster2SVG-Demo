import { elements } from "../dom.js";
import { renderState } from "../state.js?v=workspace-session-isolation-5";
import {
  captureDetailsState,
  createCollapsibleContent,
  formatDate,
  restoreDetailsState,
  stableStringify,
} from "../utils.js";

export function renderMessages(messages, run, linkedMessageIndex, onMessageSelect) {
  const signature = stableStringify({
    messages: messages || [],
    selectedMessageIndex: linkedMessageIndex,
    selectedRunId: run?.run_id || null,
  });
  if (renderState.messagesSig === signature) {
    return;
  }

  const detailsState = captureDetailsState(elements.messages);
  const nearBottom = elements.messages.scrollHeight - elements.messages.scrollTop - elements.messages.clientHeight < 48;
  elements.messages.innerHTML = "";

  for (const [index, message] of (messages || []).entries()) {
    const bubble = document.createElement("article");
    bubble.className = `message ${message.role}${linkedMessageIndex === index ? " selected" : ""}`;
    bubble.dataset.messageIndex = String(index);
    bubble.addEventListener("click", () => onMessageSelect(index, message));

    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = `${message.role} | ${formatDate(message.created_at)}`;
    bubble.appendChild(meta);
    bubble.appendChild(
      createCollapsibleContent(message.content, {
        maxLength: 420,
        key: `message:${index}:${message.created_at}`,
      })
    );
    elements.messages.appendChild(bubble);
  }

  restoreDetailsState(elements.messages, detailsState);
  if (nearBottom) {
    elements.messages.scrollTop = elements.messages.scrollHeight;
  }
  renderState.messagesSig = signature;
}

export function renderApproval(approvalRequest) {
  const signature = stableStringify(approvalRequest || null);
  if (renderState.approvalSig === signature) {
    return;
  }

  if (!approvalRequest) {
    elements.approvalBox.classList.add("hidden");
    elements.approvalSummary.textContent = "";
    elements.approvalPayload.textContent = "";
    elements.approvalComment.value = "";
    elements.approvalComment.disabled = false;
    elements.approveBtn.disabled = false;
    elements.rejectBtn.disabled = false;
    renderState.approvalSig = signature;
    return;
  }

  elements.approvalSummary.textContent = `${approvalRequest.action_summary} Approval resume is retired; use Resume Run from saved artifacts instead.`;
  elements.approvalPayload.textContent = JSON.stringify(approvalRequest.payload, null, 2);
  elements.approvalComment.value = "Approval resume is no longer supported in this build.";
  elements.approvalComment.disabled = true;
  elements.approveBtn.disabled = true;
  elements.rejectBtn.disabled = true;
  elements.approvalBox.classList.remove("hidden");
  renderState.approvalSig = signature;
}
