import Mention from "@tiptap/extension-mention";
import { Placeholder } from "@tiptap/extensions";
import { EditorContent, ReactRenderer, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import type { SuggestionKeyDownProps, SuggestionProps } from "@tiptap/suggestion";
import {
  forwardRef,
  type ReactNode,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import type { RichText, UserBrief } from "../api/client";
import { Avatar } from "./ui";

type Node = {
  type: string;
  text?: string;
  attrs?: Record<string, unknown>;
  marks?: { type: string; attrs?: Record<string, unknown> }[];
  content?: Node[];
};

const SAFE_HREF = /^(https?:|mailto:)/i;

/** Render stored Tiptap JSON as React elements. No HTML strings are ever injected. */
export function RichTextView({ doc, className = "" }: { doc: RichText | null | undefined; className?: string }) {
  if (!doc) return null;
  return <div className={`prose-seltzer ${className}`}>{renderChildren(doc as Node)}</div>;
}

function renderChildren(node: Node): ReactNode {
  return node.content?.map((child, i) => <RenderNode key={i} node={child} />);
}

function RenderNode({ node }: { node: Node }): ReactNode {
  const kids = renderChildren(node);
  switch (node.type) {
    case "paragraph":
      return <p>{kids}</p>;
    case "heading": {
      const level = Number(node.attrs?.level ?? 2);
      return level <= 1 ? <h1>{kids}</h1> : level === 2 ? <h2>{kids}</h2> : <h3>{kids}</h3>;
    }
    case "bulletList":
      return <ul>{kids}</ul>;
    case "orderedList":
      return <ol>{kids}</ol>;
    case "listItem":
    case "taskItem":
      return <li>{kids}</li>;
    case "taskList":
      return <ul>{kids}</ul>;
    case "blockquote":
      return <blockquote>{kids}</blockquote>;
    case "codeBlock":
      return (
        <pre>
          <code>{kids}</code>
        </pre>
      );
    case "hardBreak":
      return <br />;
    case "horizontalRule":
      return <hr className="my-2 border-line" />;
    case "mention":
      return <span className="mention">@{String(node.attrs?.label ?? "someone")}</span>;
    case "text":
      return applyMarks(node.text ?? "", node.marks ?? []);
    default:
      return kids;
  }
}

function applyMarks(text: string, marks: NonNullable<Node["marks"]>): ReactNode {
  let out: ReactNode = text;
  for (const mark of marks) {
    if (mark.type === "bold") out = <strong>{out}</strong>;
    else if (mark.type === "italic") out = <em>{out}</em>;
    else if (mark.type === "strike") out = <s>{out}</s>;
    else if (mark.type === "underline") out = <u>{out}</u>;
    else if (mark.type === "code") out = <code>{out}</code>;
    else if (mark.type === "link") {
      const href = String(mark.attrs?.href ?? "");
      out = SAFE_HREF.test(href) ? (
        <a href={href} target="_blank" rel="noopener noreferrer nofollow">
          {out}
        </a>
      ) : (
        out
      );
    }
  }
  return out;
}

export function isEmptyDoc(doc: RichText | null | undefined): boolean {
  if (!doc) return true;
  const walk = (n: Node): boolean =>
    n.type === "mention" || (n.type === "text" && !!n.text?.trim()) || (n.content ?? []).some(walk);
  return !walk(doc as Node);
}

/* Mention suggestions ----------------------------------------------------------------- */

type MentionListHandle = { onKeyDown: (props: SuggestionKeyDownProps) => boolean };

const MentionList = forwardRef<MentionListHandle, SuggestionProps<UserBrief>>(function MentionList(props, ref) {
  const [index, setIndex] = useState(0);
  useEffect(() => setIndex(0), [props.items]);
  const pick = (i: number) => {
    const user = props.items[i];
    if (user) props.command({ id: user.id, label: user.display_name });
  };
  useImperativeHandle(ref, () => ({
    onKeyDown: ({ event }) => {
      if (event.key === "ArrowDown") {
        setIndex((i) => (i + 1) % Math.max(1, props.items.length));
        return true;
      }
      if (event.key === "ArrowUp") {
        setIndex((i) => (i - 1 + props.items.length) % Math.max(1, props.items.length));
        return true;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        pick(index);
        return true;
      }
      return false;
    },
  }));
  if (!props.items.length) return null;
  return (
    <div className="min-w-48 overflow-hidden rounded-lg border border-line bg-surface p-1 shadow-lift">
      {props.items.map((user, i) => (
        <button
          type="button"
          key={user.id}
          onMouseDown={(e) => {
            e.preventDefault();
            pick(i);
          }}
          className={`flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[13px] ${
            i === index ? "bg-accent-soft" : ""
          }`}
        >
          <Avatar user={user} size={18} />
          {user.display_name}
        </button>
      ))}
    </div>
  );
});

function mentionExtension(getUsers: () => UserBrief[]) {
  return Mention.configure({
    HTMLAttributes: { class: "mention" },
    renderText: ({ node }) => `@${node.attrs.label ?? ""}`,
    suggestion: {
      items: ({ query }) =>
        getUsers()
          .filter((u) => u.display_name.toLowerCase().includes(query.toLowerCase()))
          .slice(0, 6),
      render: () => {
        let renderer: ReactRenderer<MentionListHandle, SuggestionProps<UserBrief>> | null = null;
        let box: HTMLDivElement | null = null;
        const place = (props: SuggestionProps<UserBrief>) => {
          const rect = props.clientRect?.();
          if (!rect || !box) return;
          box.style.left = `${rect.left + window.scrollX}px`;
          box.style.top = `${rect.bottom + window.scrollY + 4}px`;
        };
        return {
          onStart: (props) => {
            renderer = new ReactRenderer(MentionList, { props, editor: props.editor });
            box = document.createElement("div");
            box.style.position = "absolute";
            box.style.zIndex = "60";
            box.appendChild(renderer.element);
            document.body.appendChild(box);
            place(props);
          },
          onUpdate: (props) => {
            renderer?.updateProps(props);
            place(props);
          },
          onKeyDown: (props) => {
            if (props.event.key === "Escape") return false;
            return renderer?.ref?.onKeyDown(props) ?? false;
          },
          onExit: () => {
            box?.remove();
            renderer?.destroy();
            box = null;
            renderer = null;
          },
        };
      },
    },
  });
}

/* Editor ------------------------------------------------------------------------------- */

type EditorProps = {
  value: RichText | null | undefined;
  users: UserBrief[];
  placeholder?: string;
  autoFocus?: boolean;
  /** Called on blur with the new document when it changed. */
  onCommit?: (doc: RichText | null) => void;
  /** Called on Cmd/Ctrl+Enter. */
  onSubmit?: (doc: RichText) => void;
  onChange?: (doc: RichText) => void;
  resetKey?: unknown;
  className?: string;
};

export function RichTextEditor({
  value,
  users,
  placeholder = "Write something…",
  autoFocus = false,
  onCommit,
  onSubmit,
  onChange,
  resetKey,
  className = "",
}: EditorProps) {
  const usersRef = useRef(users);
  usersRef.current = users;
  const submitRef = useRef(onSubmit);
  submitRef.current = onSubmit;
  const initial = useRef(JSON.stringify(value ?? null));

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3] },
        link: { openOnClick: false, autolink: true, defaultProtocol: "https" },
      }),
      mentionExtension(() => usersRef.current),
      Placeholder.configure({ placeholder }),
    ],
    content: (value as object | null) ?? "",
    autofocus: autoFocus ? "end" : false,
    editorProps: {
      attributes: { "aria-label": placeholder },
      handleKeyDown: (view, event) => {
        if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && submitRef.current) {
          const doc = view.state.doc.toJSON() as RichText;
          if (!isEmptyDoc(doc)) submitRef.current(doc);
          return true;
        }
        return false;
      },
    },
    onUpdate: ({ editor: e }) => onChange?.(e.getJSON() as RichText),
    onBlur: ({ editor: e }) => {
      if (!onCommit) return;
      const doc = e.isEmpty ? null : (e.getJSON() as RichText);
      const serialized = JSON.stringify(doc);
      if (serialized !== initial.current) {
        initial.current = serialized;
        onCommit(doc);
      }
    },
  });

  // Reset content from outside (e.g. after posting a comment, or a newer server copy).
  useEffect(() => {
    if (!editor) return;
    if (editor.isFocused && resetKey === undefined) return;
    editor.commands.setContent((value as object | null) ?? "", { emitUpdate: false });
    initial.current = JSON.stringify(value ?? null);
  }, [editor, resetKey]);

  return <EditorContent editor={editor} className={`prose-seltzer ${className}`} />;
}
