import { AlertTriangleIcon, GlobeIcon, MailIcon, PhoneIcon } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { CRAWL_LABEL } from "@/lib/format";
import type { LeadOut } from "@/lib/types";
import { cn } from "@/lib/utils";

function Icon({
  state,
  label,
  children,
}: {
  state: "good" | "bad" | "none";
  label: string;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          aria-label={label}
          className={cn(
            "relative inline-flex size-6 items-center justify-center rounded-md [&_svg]:size-3.5",
            state === "good" && "text-foreground/80",
            state === "bad" && "text-muted-foreground line-through decoration-2",
            state === "none" && "text-muted-foreground/35",
          )}
        >
          {children}
          {state === "bad" && <span className="absolute h-px w-4 rotate-45 bg-muted-foreground" />}
        </span>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

export function ContactIcons({ lead }: { lead: LeadOut }) {
  const email =
    lead.email_status === "valid_mx"
      ? (["good", "Company email · domain accepts mail (MX)"] as const)
      : lead.email_status === "no_mx"
        ? (["bad", "Company email found, but its domain has no mail server"] as const)
        : lead.email_status === "invalid"
          ? (["bad", "Email found but malformed"] as const)
          : (["none", "No company email published"] as const);
  const phone =
    lead.phone_valid === true
      ? (["good", "Phone number is valid"] as const)
      : lead.phone_valid === false
        ? (["bad", "Phone number looks invalid"] as const)
        : (["none", "No phone listed"] as const);
  const cs = lead.crawl_status ?? "no_site";
  return (
    <span className="flex items-center gap-0.5">
      <Icon state={phone[0]} label={phone[1]}>
        <PhoneIcon />
      </Icon>
      <Icon state={email[0]} label={email[1]}>
        <MailIcon />
      </Icon>
      {cs === "ok" ? (
        <Icon state="good" label={CRAWL_LABEL.ok}>
          <GlobeIcon />
        </Icon>
      ) : (
        <Tooltip>
          <TooltipTrigger asChild>
            <span
              aria-label={CRAWL_LABEL[cs]}
              className="inline-flex size-6 items-center justify-center rounded-md text-warn [&_svg]:size-3.5"
            >
              <AlertTriangleIcon />
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-64">{CRAWL_LABEL[cs]}</TooltipContent>
        </Tooltip>
      )}
    </span>
  );
}
