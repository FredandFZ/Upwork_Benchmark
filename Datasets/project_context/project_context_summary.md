# Project Context Extraction Summary

This package contains project-background and engineering-context extraction only.

## Coverage

- Selected project IDs: 55
- Projects found: 55
- Projects not found: 0
- Successfully processed projects: 55
- HIGH context quality: 2
- MEDIUM context quality: 44
- LOW context quality: 9
- INSUFFICIENT context quality: 0
- Projects with inspectable local source/engineering files: 2
- Projects with external repository references: 2
- External repositories successfully inspected: 0
- Projects with strong architecture information: 2
- Projects with strong technical-stack information: 2
- Projects with strong codebase understanding: 1
- Projects requiring manual review: 13

## Projects requiring manual review

35648772, 41712429, 44041890, 44063994, 44100158, 44113196, 44159206, 44159601, 44166278, 44190396, 44194756, 44199774, 44202166

## Common missing-information patterns

- Most projects do not include an inspectable software repository, so code structure, verified setup commands, APIs, automated tests, and deployment details remain unknown.
- Several engagements are design, editorial, legal, media, or operations projects; runtime software architecture is not applicable and artifact workflow is recorded instead.
- External repository links found in conversation could not be fetched in the current environment and are recorded without claiming code inspection.
- Audio/video binaries were inventoried but not transcribed; surrounding conversation was used for production context.
- RAR archives could not be expanded; their filenames and conversation context are retained and flagged for review.

## Common source types used

Job descriptions and metadata established the initial purpose; full conversations supplied workflow, constraints, terminology, and review history; Word, PDF, spreadsheet, presentation, image/OCR, engineering, and source-code deliverables supplied richer artifact and technical evidence.

## Conflicts and leakage controls

No unsupported single truth was forced when source certainty was weak. Long conversations and final deliverables may contain late requirement outcomes, so numeric values, temporary status, and changing provider choices are not encoded as timeless background facts. Each project records its own potential leakage risks and unknowns.
