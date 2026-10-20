---
name: VineSearch
description: Private discovery with precise working typography and neutral surfaces
colors:
  accent: "#a54420"
  accent-hover: "#793518"
  ground: "#f4f5f7"
  surface: "#fbfcfd"
  ink: "#1a1a1a"
  secondary: "#4a4a4a"
  muted: "#60656c"
  rule: "#d3d7dc"
  selected: "#eceef1"
  good: "#3e683b"
  bad: "#a02d2d"
  warning: "#775609"
typography:
  display:
    fontFamily: '"DM Serif Display", Georgia, serif'
    fontSize: "32px"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  headline:
    fontFamily: '"IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "20px"
    fontWeight: 500
    lineHeight: 1.35
  body:
    fontFamily: '"IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: '"IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.5
  metadata:
    fontFamily: '"IBM Plex Mono", monospace'
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.5
  small-body:
    fontFamily: '"IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
  product-title:
    fontFamily: '"IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "15px"
    fontWeight: 500
    lineHeight: 1.45
  product-title-mobile:
    fontFamily: '"IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "14px"
    fontWeight: 500
    lineHeight: 1.45
  wordmark:
    fontFamily: '"IBM Plex Mono", monospace'
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  panel-title:
    fontFamily: '"IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "17px"
    fontWeight: 500
    lineHeight: 1.35
  tracker-title:
    fontFamily: '"IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "18px"
    fontWeight: 500
    lineHeight: 1.35
  empty-mobile:
    fontFamily: '"DM Serif Display", Georgia, serif'
    fontSize: "23px"
    fontWeight: 400
    lineHeight: 1.35
  empty-title:
    fontFamily: '"DM Serif Display", Georgia, serif'
    fontSize: "25px"
    fontWeight: 400
    lineHeight: 1.35
  display-mobile:
    fontFamily: '"DM Serif Display", Georgia, serif'
    fontSize: "28px"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  display-tablet:
    fontFamily: '"DM Serif Display", Georgia, serif'
    fontSize: "29px"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: "-0.01em"
rounded:
  control: "3px"
  tag: "2px"
spacing:
  xs: "6px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "{colors.surface}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.accent}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "9px 11px"
  product-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
---

# Design System: VineSearch

## Overview

The working catalog is the visual reference: products lead, controls remain familiar, and observed evidence has a stable place beside each item. Architectural alignment and modest typography carry the ATM identity without consuming the task space. Neutral ground and near-white card surfaces support product images, readable titles and useful filters.

## Colors

Terracotta is the interactive accent, darkened from the general brand token to preserve ordinary-text contrast on the delivered neutral surfaces. Neutral ground and near-white surfaces create a quiet hierarchy; dividers define grouping. Green, red and muted ochre carry success, error and partial-result states, always with accompanying text.

Cream, beige, parchment and warm-white surfaces are excluded. Pure black and pure white are not interface tokens. Link, control and focus treatments use the same accent vocabulary throughout the application.

## Typography

IBM Plex Sans carries working labels, controls, titles and explanatory copy. DM Serif Display appears only at regular weight in page and empty-state headings. IBM Plex Mono is reserved for compact provenance, identity and measured score values.

Page titles follow the display, display-tablet and display-mobile roles while retaining the same compact line height. Product titles use the product-title role, changing to product-title-mobile on phones, and wrap without truncating the evidence. General body text drops from the body role to 14px on phones, while explanatory paragraphs stay within 70 characters of reading width. Bundled font files and their SIL Open Font License notices ship in `src/vine_search/static/fonts/`; there are no third-party font requests.

## Layout

The page container caps at 1500px with 32px desktop gutters and 16px phone gutters. Discovery uses a 192px filter rail, narrowing to 172px at the compact-desktop breakpoint and 152px at the tablet breakpoint. Four product columns appear at 1350px and wider, three by default, and two at 1100px and narrower. At 600px and narrower, each card becomes a horizontal record with a 112px image column and filters become an explicit disclosure.

Navigation moves to its own visible header row at 800px and narrower, when the tracker editor also moves below the tracker list and settings navigation moves above the form. Review rows become labeled records at the phone breakpoint. Settings and tracker form fields use two columns where useful and one column on phones, preserving readable labels and native controls. The save-settings action sticks to the bottom of the viewport while its form remains in view.

## Elevation & Depth

Panels use a structural border with no shadow. A single transient toast has soft elevation (`0 4px 20px #1a1a1a20`); confirmation dialogs use the native dialog backdrop. Product cards do not lift or animate on hover because scanning and selecting remain the priority.

## Shapes

Corners are almost square, with 3px control/container radii and 2px tags. Border lines separate content and establish active navigation. Status dots are accompanied by text; no meaning depends on color or shape alone.

## Components

Buttons use one consistent vocabulary: primary filled terracotta, secondary outlined neutral, and subtle text action. Controls have visible focus outlines and disabled states; hover changes color and border over 160ms. Native inputs, checkboxes, selects and dialogs retain familiar behavior.

The search surface explicitly labels collected history and live Amazon search. The live-job strip shows saved progress and cancellation without blocking the catalog. Product cards align image, source, title, category, deterministic match explanation and last-seen evidence. Image failure produces a labeled unavailable state.

Tracker editing remains beside its list on desktop and flows beneath it at the tablet breakpoint. Review status uses separate columns for Amazon's observation and manual local progress. Notification destinations and secrets are write-only inputs, with explicit replacement/removal choices.

Keyboard users have a skip-to-content link, native form controls and a two-pixel focus outline with a three-pixel offset. Main navigation marks the current route; source buttons expose their pressed state and the phone filter control exposes whether its region is expanded. Loading marks the main region busy, while connection notices, live-job progress and transient messages use polite status announcements. Reduced-motion preferences disable transitions, skeleton animation and smooth scrolling. These are implemented accessibility contracts; simulated viewport checks do not establish physical-phone or assistive-technology behavior.

Coverage text names the recent source scopes and distinguishes mixed historical runs from one selected live-search run. Date-only order and target values preserve their calendar date across browser timezones, while timestamp displays retain their time context. Local review progress updates the displayed counters and removes a changed record from an incompatible progress filter; this never changes the observed Amazon status. Startup retry restores initialization before settings can be saved, and deletion help and confirmation explicitly preserve settings and tracker rules. The independent correction verdict and its evidence boundaries are recorded in `docs/qa-review.md`.

## Do's and Don'ts

- Do keep timestamps, scopes and partial-result states near their observations.
- Do preserve neutral surfaces, local font delivery, visible keyboard focus and text-based state explanations.
- Do let real product titles wrap and design the narrow layout structurally.
- Don't substitute charts, marketing headlines or decorative metrics for discovery content.
- Don't use bold DM Serif Display, rounded pill containers or cream backgrounds.
- Don't use color alone for status, return stored secrets into forms, or call history results live inventory.

## Live-use additions

Product cards separate Open product from See details. The latter uses a native
read-only dialog with queued, running, observed and unavailable states; an unknown
ETV remains explicitly unavailable. Selection checkboxes and a selected-item
 toolbar support hide/restore on the displayed page. Review rows include thumbnails
under the same image policy and retain separate observed status and local progress.

Help has directly addressable topics for discovery, trackers, literal matching,
scoring, schedules, notifications, connection, reviews, visibility and recovery.
Contextual links open help separately to preserve an active form. The tracker
editor brings invalid fields into view, keeps drafts while moving between app
views, and confirms the saved identity in a fresh list read before announcing
success. A pending confirmation retains entries and offers a list refresh rather
than another create request.

Discovery labels queue refresh and query search separately. Search help states
that both manual and scheduled searches traverse all exposed result pages; queue
and review bounds are described only where they apply. Live-result counts separate
captured inventory from the current filtered view, with a direct filter reset.
