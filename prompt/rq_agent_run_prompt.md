# ReqMemBench isolated Phase A run

This is one isolated benchmark case. The complete contents of the four public
input files are embedded after these instructions:

- `task.json`
- `history.jsonl`
- `instructions.md`
- `response.schema.json`

Read all four embedded file sections before answering. Complete the task in
`task.json` using only the evidence visible in `history.jsonl`, and follow
`instructions.md` exactly. Do not call shell, filesystem, web, MCP, connector,
or other tools; every authorized input is already embedded in this prompt.

Do not inspect parent directories, external repositories, previous runs, or any
file not listed above. Do not use information remembered from another task or
condition. There is no continuing conversation: this run starts and ends with
this case.

Return exactly one JSON object conforming to `response.schema.json`. Do not wrap
the object in Markdown and do not add prose outside the JSON object.
