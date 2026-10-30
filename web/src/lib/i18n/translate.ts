import zh from "./zh.json";
import { translateBusinessText } from "./business-text";

export type Locale = "zh" | "en";
export type Translator = <T>(value: T, params?: readonly unknown[]) => T;
const dictionary: Readonly<Record<string, string>> = zh;
const normalize = (text: string) => text.replace(/\s+/g, " ").trim();
const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const patterns = Object.entries(dictionary)
  .filter(([key]) => /\{\d+\}/.test(key))
  .sort(
    ([a], [b]) =>
      b.replace(/\{\d+\}/g, "").length - a.replace(/\{\d+\}/g, "").length,
  )
  .map(([key, value]) => {
    const indices: number[] = [];
    const expression = key
      .split(/(\{\d+\})/)
      .map((part) => {
        if (/^\{\d+\}$/.test(part)) {
          indices.push(Number(part.slice(1, -1)));
          return "(.*?)";
        }
        return escape(part);
      })
      .join("");
    return { regex: new RegExp(`^${expression}$`), value, indices };
  });

/** Rendered strings only. Numbers, React elements, arrays and canonical payloads stay intact. */
export function translate<T>(
  locale: Locale,
  value: T,
  params?: readonly unknown[],
): T {
  if (typeof value !== "string") return value;
  const key = normalize(value);
  const http = key.match(/^(.*?) \[HTTP (\d{3})\]$/);
  if (locale === "zh" && http) {
    const localized = translate("zh", http[1]);
    const message =
      localized === http[1] && !/[\u3400-\u9fff]/.test(http[1])
        ? "请求未成功，请检查输入、登录状态或服务连接。技术信息：" + http[1]
        : localized;
    return `${message} [HTTP ${http[2]}]` as T;
  }
  let result: string = value;
  if (locale === "zh") {
    result =
      dictionary[key] ??
      translateBusinessText(
        key,
        (part) => translate("zh", part),
        (part) => dictionary[part] ?? part,
      );
    if (result === key && !dictionary[key]) {
      for (const pattern of patterns) {
        const match = key.match(pattern.regex);
        if (match) {
          const values: string[] = [];
          pattern.indices.forEach((index, i) => {
            values[index] = dictionary[match[i + 1]] ?? match[i + 1];
          });
          result = pattern.value.replace(
            /\{(\d+)\}/g,
            (_, index) => values[Number(index)] ?? "",
          );
          break;
        }
      }
    }
  }
  // Unknown source/user text must keep whitespace, especially controlled note inputs.
  if (locale === "zh" && !dictionary[key] && result === key) result = value;
  if (params)
    result = result.replace(/\{(\d+)\}/g, (_, index) =>
      String(params[Number(index)] ?? ""),
    );
  return result as T;
}

/** Editable source text: only an exact, known catalog default may be localized. */
export function translateExact(locale: Locale, value: string): string {
  return locale === "zh" ? (dictionary[value] ?? value) : value;
}
