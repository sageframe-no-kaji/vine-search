# VineSearch product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python, FastAPI, SQLite and a separate Playwright collector; server-rendered HTML with small vanilla JavaScript updates. One distributable Docker image supplies the web and collector roles.

## Users

One Amazon.com Vine participant per privately hosted installation. They scan products and review progress on a phone or desktop while the server performs scheduled collection independently of their daily browser.

## Product Purpose

Find relevant Vine products through live Additional Items searches and timestamped collected history, maintain editable discovery interests, and track review work without ordering products or writing/posting reviews.

## Positioning

Self-hosted, public-source discovery with no required extension, paid AI provider, shared inventory service, subscription or cloud identity provider. Optional notifications and Amazon image requests have explicit network destinations.

## Operating Context

The operator opens the private dashboard over their own private network. A temporary browser viewer lets them sign in directly on Amazon, including MFA; the dedicated server browser then resumes headless collection. Login and all collection share one serial queue. Dashboard history remains useful when Amazon is unavailable.

## Capabilities and Constraints

Live catalog search and collected-history search are distinct. RFY, AFA, saved searches, review sync, matching and notification settings are editable. Product identity, scope, timestamps, partial collection and uncertainty remain visible. Unknown categories cannot satisfy restricted categories. Local review progress is separate from observed Amazon status. Imports whitelist metadata and exclude writing, photos, notes and credentials. Ordering, review posting, AI writing, multi-user accounts, dark mode and a native app are outside the MVP.

## Brand Commitments

VineSearch uses the ATM typography and architectural visual language with neutral ground, near-white surfaces and restrained terracotta interactions. Cream backgrounds are excluded. Product images, readable titles and useful filters lead the interface; fonts and other required assets ship with the application.

## Evidence on Hand

Interface fixtures and public captures use explicitly synthetic metadata. The [release verification report](docs/release-verification.md) records automated checks, container exercises and the separate status of live-account and deployment verification. Synthetic observations do not establish Amazon compatibility.

## Product Principles

- Preserve the distinction between observation and current availability.
- Make a useful discovery action reachable in one screen.
- Keep settings proportional to meaningful operator choices.
- Preserve private history across interruptions and reconnects.
- Explain rank, delivery and coverage in the same vocabulary as their controls.

## Accessibility & Inclusion

Keyboard navigation, visible focus, contrast of at least 4.5:1 for ordinary text, comfortable mobile touch controls, semantic forms and status announcements. Required simulated viewport checks: 360px, 390px, tablet and desktop. Physical-phone verification is separate.
