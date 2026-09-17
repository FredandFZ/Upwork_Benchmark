export function assertBalancedSExpression(text, label = "s-expression") {
  let depth = 0;
  let quoted = false;
  let escaped = false;
  for (const character of text) {
    if (quoted) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === '"') quoted = false;
      continue;
    }
    if (character === '"') quoted = true;
    else if (character === "(") depth += 1;
    else if (character === ")") {
      depth -= 1;
      if (depth < 0) throw new Error(`${label} closes before it opens`);
    }
  }
  if (quoted || depth !== 0) throw new Error(`${label} is not balanced`);
  return true;
}

export function quoteSExpression(value) {
  return `"${String(value).replaceAll("\\", "\\\\").replaceAll('"', '\\"').replace(/[\r\n]+/g, " ")}"`;
}
