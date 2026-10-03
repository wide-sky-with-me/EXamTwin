import { screen, waitFor } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";

/** The Ant Design Select root, whose text is the selected label or the placeholder. */
export function selectRoot(label: string): HTMLElement {
  const root = screen.getByLabelText(label).closest<HTMLElement>(".ant-select");
  if (!root) throw new Error(`${label} is not an Ant Design Select`);
  return root;
}

/** Opens the labelled Select and clicks the option whose text contains `text`. */
export async function chooseSelectOption(user: UserEvent, label: string, text: string) {
  await user.click(screen.getByLabelText(label));
  const option = await waitFor(() => {
    const match = [...document.querySelectorAll<HTMLElement>(".ant-select-item-option")]
      .reverse()
      .find((node) => node.textContent?.includes(text));
    if (!match) throw new Error(`option containing ${text} was not rendered`);
    return match;
  });
  await user.click(option);
}
