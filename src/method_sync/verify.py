"""Команда перевірки: живий виклик через клієнт бібліотеки і звіряння полів та енамів в обидва боки (FR-31–FR-53).

Це те, що робить принцип IV перевіркою, а не наміром. Три речі з v1 тут не косметичні, кожна доведена пробою і кожна
ламається мовчки:

1. Раннер генерується в тимчасовому каталозі ІНСТРУМЕНТА, а не в цільовій бібліотеці (FR-32). Інакше прогін без
   розходжень лишав би по собі новий файл, і «порожній diff» був би невиконанним.
2. Раннер зобов'язаний явно завершити JVM на кожному шляху (FR-42). Клієнт бібліотеки лишає живими не-демонські
   потоки, тож без `System.exit` процес не виходить навіть після успішного результату.
3. Строгої десеріалізації самої по собі не досить: зайве поле моделі вона не ловить (перевірено на Jackson 2.10.1).
   Зворотний бік — окреме звіряння множин.

Відмінності від v1 (design.md): виняток клієнта перехоплюється і йде в `client_error`, а звіряння йде далі (FR-46);
енамні поля верхнього рівня звіряються за принципом «живе ⊆ оголошене» (FR-47–FR-53); поля моделі — властивості, у
які Jackson десеріалізує (FR-36); переліки — за кодовими точками Unicode (FR-41); збій стадії — вердикт
`{green, stage, reason[, limit_s]}`, а не виняток (FR-43), і кожна стадія має ліміт часу (NFR-2, NFR-5).
"""
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

ENVELOPE_CLASS = "com.example.delays.Response"
ENVELOPE_FIELDS = ("requestSent", "responseRecv")

DEFAULT_FACTORY = "com.example.binanceFutures.general.BinanceFuturesApiClientFactory"
DEFAULT_REST_CLIENT = "com.example.binanceFutures.general.BinanceFuturesApiRestClient"

RUNNER_CLASS = "MethodSyncVerify"
VERDICT_KEYS = ("green", "model", "live", "extra", "missing", "owners", "client_error", "enums")

# Стадії в порядку виконання (FR-43) і їхній опис для звіту (FR-80): звіт не може писати «розходжень немає» там, де
# порівняння не було (принцип IV). `compile` називає команду, а на ліміті — ще й ліміт.
STAGES = ("compile", "workdir", "classpath", "javac", "timeout", "runner")
STAGE_LABEL = {
    "compile": "команда перевірки не пройшла ({verify_cmd})",
    "workdir": "каталог раннера опинився всередині бібліотеки",
    "classpath": "класпас не зібрався",
    "javac": "раннер не зібрався",
    "timeout": "раннер не завершився вчасно",
    "runner": "раннер не дав придатного вердикту",
}
COMPILE_LIMIT_LABEL = "команда перевірки не завершилась за {limit} с ({verify_cmd})"

VERIFY_TIMEOUT_SECONDS = 600
CLASSPATH_TIMEOUT_SECONDS = 300
JAVAC_TIMEOUT_SECONDS = 300
RUNNER_TIMEOUT_SECONDS = 120

# Сирий рядок: `\\R` мусить дійти до Java як є.
_TEMPLATE = r"""
import com.fasterxml.jackson.annotation.JsonEnumDefaultValue;
import com.fasterxml.jackson.databind.BeanDescription;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JavaType;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;
import com.fasterxml.jackson.databind.introspect.BeanPropertyDefinition;
import __FACTORY__;
import __REST_CLIENT__;
import __MODEL__;

import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.PrintStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Згенеровано method-sync. Живий виклик через клієнт бібліотеки + звіряння полів і енамів в обидва боки. */
public class __RUNNER__ {

    private static final List<String> ENVELOPE = List.of(__ENVELOPE__);
    private static final String ENVELOPE_CLASS = __ENVELOPE_CLASS__;
    private static final Comparator<String> BY_CODE_POINT = __RUNNER__::byCodePoint;
    private static final int VALUE = 1;
    private static final int COLLECTION = 2;
    private static final int MAP_KEYS = 3;

    public static void main(String[] args) {
        // Вивід — UTF-8 незалежно від локалі процесу: людський лог кирилицею, ключі JSON — будь-які.
        System.setOut(new PrintStream(new FileOutputStream(FileDescriptor.out), true, StandardCharsets.UTF_8));
        String clientError = null;
        try {
            final __REST_CLIENT_SIMPLE__ client = __FACTORY_SIMPLE__.newInstance().newFuturesRestClient();
            final Object result = client.__CLIENT_METHOD__(__CALL_ARGS__);
            System.out.println("клієнт бібліотеки повернув: " + result);
        } catch (Throwable error) {
            // FR-46: виняток клієнта не зупиняє звіряння — сирий JSON береться окремо, а вердикт буде червоним.
            clientError = error.toString();
            System.out.println("клієнт бібліотеки кинув виняток: " + clientError);
        }
        try {
            // Без явного виходу JVM не завершується: клієнт тримає не-демонські потоки (FR-42).
            if (compare(clientError)) {
                System.exit(0);
            }
            System.exit(1);
        } catch (Throwable error) {
            // FR-43: вердикту немає, останній рядок — сам виняток одним рядком; перевірка дасть стадію runner.
            System.out.println(error.toString().replaceAll("\\R", " "));
            System.exit(1);
        }
    }

    private static boolean compare(String clientError) throws Exception {
        // FR-35: живі ключі і значення — лише із сирого JSON рівно за URL фікстури; перенаправлень HttpClient
        // типово не виконує.
        final String body = HttpClient.newHttpClient().send(
                HttpRequest.newBuilder(URI.create(__URL__)).build(),
                HttpResponse.BodyHandlers.ofString()).body();

        final ObjectMapper mapper = new ObjectMapper();
        final JsonNode node = mapper.readTree(body);
        final List<JsonNode> objects = new ArrayList<>();
        if (node.isArray()) {
            node.forEach(objects::add);
        } else {
            objects.add(node);
        }

        // FR-38: об'єднання ключів по ВСІХ об'єктах верхнього рівня, а не по першому елементу масиву.
        final Set<String> live = new TreeSet<>(BY_CODE_POINT);
        for (JsonNode item : objects) {
            item.fieldNames().forEachRemaining(live::add);
        }

        // FR-36: поля моделі — властивості, у які Jackson десеріалізує (є мутатор), а не рефлексія по полях класу.
        final BeanDescription description = mapper.getDeserializationConfig()
                .introspect(mapper.getTypeFactory().constructType(__MODEL_SIMPLE__.class));
        final Set<String> model = new TreeSet<>(BY_CODE_POINT);
        final Map<String, String> owners = new TreeMap<>(BY_CODE_POINT);
        final Map<String, JavaType> types = new TreeMap<>(BY_CODE_POINT);
        for (BeanPropertyDefinition property : description.findProperties()) {
            if (property.getMutator() == null) {
                continue;  // лише гетер: у таку властивість Jackson не десеріалізує
            }
            final String owner = property.getPrimaryMember().getDeclaringClass().getName();
            // FR-37: поля-конверт біржа не віддає ніколи — без виключення перевірка не позеленіла б.
            if (ENVELOPE.contains(property.getName()) && owner.equals(ENVELOPE_CLASS)) {
                continue;
            }
            model.add(property.getName());
            owners.put(property.getName(), owner);
            types.put(property.getName(), property.getPrimaryType());
        }

        final Set<String> extra = new TreeSet<>(BY_CODE_POINT);
        extra.addAll(model);
        extra.removeAll(live);
        final Set<String> missing = new TreeSet<>(BY_CODE_POINT);
        missing.addAll(live);
        missing.removeAll(model);

        System.out.println("модель = " + model);
        System.out.println("жива   = " + live);
        System.out.println("ЗАЙВІ в моделі  = " + extra);
        System.out.println("БРАКУЄ в моделі = " + missing);

        // FR-47–FR-53: енамні поля верхнього рівня за принципом «живе ⊆ оголошене».
        final List<Map<String, Object>> enums = new ArrayList<>();
        boolean enumsGreen = true;
        for (Map.Entry<String, JavaType> entry : types.entrySet()) {
            final int shape = enumShape(entry.getValue());
            if (shape == 0) {
                continue;
            }
            final String field = entry.getKey();
            final Class<?> enumClass = enumClass(entry.getValue(), shape);
            final ObjectReader reader = mapper.readerFor(enumClass)
                    .with(DeserializationFeature.READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE);

            // FR-50: оголошені — імена констант так, як їх мапить Jackson, без запасника @JsonEnumDefaultValue.
            final Set<String> declared = new TreeSet<>(BY_CODE_POINT);
            for (Object constant : enumClass.getEnumConstants()) {
                final String name = ((Enum<?>) constant).name();
                if (!enumClass.getField(name).isAnnotationPresent(JsonEnumDefaultValue.class)) {
                    declared.add(jsonName(mapper, constant));
                }
            }
            final Set<String> values = liveValues(objects, field, shape);
            // FR-51: розходження — живе значення, яке Jackson не зводить до константи з тим самим JSON-ім'ям;
            // живе ім'я самого запасника — оголошене.
            final Set<String> undeclared = new TreeSet<>(BY_CODE_POINT);
            for (String value : values) {
                if (!isDeclared(mapper, reader, value)) {
                    undeclared.add(value);
                }
            }
            // FR-53: невидима константа лише називається, вердикт не червонить.
            final Set<String> unseen = new TreeSet<>(BY_CODE_POINT);
            unseen.addAll(declared);
            unseen.removeAll(values);

            final Map<String, Object> record = new LinkedHashMap<>();
            record.put("field", field);
            record.put("enum", enumClass.getName());
            record.put("declared", new ArrayList<>(declared));
            record.put("live", new ArrayList<>(values));
            record.put("missing", new ArrayList<>(undeclared));
            record.put("unseen", new ArrayList<>(unseen));
            enums.add(record);
            enumsGreen &= undeclared.isEmpty();
            System.out.println("енам " + field + " (" + enumClass.getName() + "): оголошені = " + declared
                    + ", живі = " + values + ", БРАКУЄ в енамі = " + undeclared + ", невидимі = " + unseen);
        }

        final boolean green = extra.isEmpty() && missing.isEmpty() && enumsGreen && clientError == null;
        final Map<String, Object> verdict = new LinkedHashMap<>();
        verdict.put("green", green);
        verdict.put("model", new ArrayList<>(model));
        verdict.put("live", new ArrayList<>(live));
        verdict.put("extra", new ArrayList<>(extra));
        verdict.put("missing", new ArrayList<>(missing));
        verdict.put("owners", owners);
        verdict.put("client_error", clientError);
        verdict.put("enums", enums);
        System.out.println(mapper.writeValueAsString(verdict));
        return green;
    }

    /** Що в JSON несе значення енама: саме значення, елементи масиву чи ключі об'єкта; 0 — не енамне поле. */
    private static int enumShape(JavaType type) {
        if (type.isEnumType()) {
            return VALUE;
        }
        final Class<?> raw = type.getRawClass();
        final boolean collection = type.isArrayType() || List.class.isAssignableFrom(raw)
                || Set.class.isAssignableFrom(raw);
        if (collection && type.getContentType() != null && type.getContentType().isEnumType()) {
            return COLLECTION;
        }
        if (type.isMapLikeType() && type.getKeyType() != null && type.getKeyType().isEnumType()) {
            return MAP_KEYS;
        }
        return 0;
    }

    private static Class<?> enumClass(JavaType type, int shape) {
        if (shape == VALUE) {
            return type.getRawClass();
        }
        return shape == COLLECTION ? type.getContentType().getRawClass() : type.getKeyType().getRawClass();
    }

    /** FR-48, FR-49: рядкові значення за JSON-ім'ям поля по всіх об'єктах; null і чужі типи значень не дають. */
    private static Set<String> liveValues(List<JsonNode> objects, String field, int shape) {
        final Set<String> values = new TreeSet<>(BY_CODE_POINT);
        for (JsonNode item : objects) {
            final JsonNode value = item.get(field);
            if (value == null) {
                continue;
            }
            if (shape == VALUE && value.isTextual()) {
                values.add(value.textValue());
            } else if (shape == COLLECTION && value.isArray()) {
                for (JsonNode element : value) {
                    if (element.isTextual()) {
                        values.add(element.textValue());
                    }
                }
            } else if (shape == MAP_KEYS && value.isObject()) {
                value.fieldNames().forEachRemaining(values::add);
            }
        }
        return values;
    }

    /** Jackson десеріалізує значення (з запасником для невідомих) у константу, чиє JSON-ім'я — рівно це значення. */
    private static boolean isDeclared(ObjectMapper mapper, ObjectReader reader, String value) {
        try {
            final Object constant = reader.readValue(mapper.writeValueAsString(value));
            return constant != null && jsonName(mapper, constant).equals(value);
        } catch (Exception error) {
            return false;  // жодної константи для цього значення Jackson не знаходить
        }
    }

    private static String jsonName(ObjectMapper mapper, Object constant) {
        return mapper.valueToTree(constant).asText();
    }

    /** Порядок за кодовими точками Unicode, як `sorted` над `str` у Python (FR-41). */
    private static int byCodePoint(String left, String right) {
        int i = 0;
        int j = 0;
        while (i < left.length() && j < right.length()) {
            final int a = left.codePointAt(i);
            final int b = right.codePointAt(j);
            if (a != b) {
                return Integer.compare(a, b);
            }
            i += Character.charCount(a);
            j += Character.charCount(b);
        }
        return Integer.compare(left.length() - i, right.length() - j);
    }
}
"""

_TOKEN = re.compile(r"__([A-Z]+(?:_[A-Z]+)*)__")


class StageFailed(Exception):
    """Стадія перевірки не пройшла: звіряння не відбулося, `verdict` — червоний вердикт стадії (FR-43)."""

    def __init__(self, stage, reason, limit=None):
        super().__init__(reason)
        self.verdict = stage_verdict(stage, reason, limit)


def stage_verdict(stage, reason, limit=None):
    """Вердикт стадії: рівно `green`, `stage`, `reason` і, на ліміті часу, `limit_s` (FR-43)."""
    verdict = {"green": False, "stage": stage, "reason": reason}
    if limit is not None:
        verdict["limit_s"] = limit
    return verdict


def seconds(limit):
    """Ліміт у секундах словами без зайвих нулів: `600`, `0.5`, `0.01`."""
    return f"{limit:g}" if isinstance(limit, float) else str(limit)


def runner_dir(lib):
    """Каталог для згенерованого раннера — завжди поза цільовою бібліотекою (FR-32, принцип VII).

    Корінь тимчасових каталогів звіряється з `lib` за реальними шляхами ДО створення каталогу раннера, тож
    `TMPDIR` усередині бібліотеки дає стадію `workdir`, а під `lib` не з'являється нічого.
    """
    try:
        root = pathlib.Path(tempfile.gettempdir()).resolve()
        home = pathlib.Path(lib).resolve()
    except (OSError, RuntimeError) as error:
        raise StageFailed("workdir", f"каталог раннера не визначено: {error}") from error
    if root.is_relative_to(home):
        raise StageFailed("workdir", f"корінь тимчасових каталогів {root} лежить у бібліотеці {home} — раннер "
                                     "генерується лише поза бібліотекою")
    try:
        return pathlib.Path(tempfile.mkdtemp(prefix="method-sync-verify-", dir=root))
    except OSError as error:
        raise StageFailed("workdir", f"каталог раннера не створено в {root}: {error}") from error


def java_literal(value):
    """Значення з реєстру → літерал Java, як у v1 (FR-34): що з цього приймає Java, вирішує `javac`."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace('"', '\\"') + '"'
    return str(value)


def _java_string(text):
    """Рядок інструмента (URL, імена класів) → повністю екранований рядковий літерал Java."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    return f'"{escaped}"'


def call_arguments(args, call=None):
    """Аргументи виклику клієнтського методу рядком Java — один і той самий для раннера і для брифу.

    Явний `call` з реєстру перемагає, зокрема порожній: коли підпис бібліотеки ширший за `args`, людина пише
    аргументи дослівно (FR-8, FR-34).
    """
    if call is not None:
        return call
    return ", ".join(java_literal(value) for value in args.values())


def render_runner(model, client_method, args, url, call=None,
                  factory=DEFAULT_FACTORY, rest_client=DEFAULT_REST_CLIENT):
    """Зібрати вихідний код раннера під конкретний метод реєстру.

    Підстановка — один прохід по шаблону: значення з реєстру, що випадково схожі на маркер, не підставляються вдруге.
    """
    replacements = {
        "FACTORY": factory,
        "FACTORY_SIMPLE": factory.rsplit(".", 1)[-1],
        "REST_CLIENT": rest_client,
        "REST_CLIENT_SIMPLE": rest_client.rsplit(".", 1)[-1],
        "MODEL": model,
        "MODEL_SIMPLE": model.rsplit(".", 1)[-1],
        "RUNNER": RUNNER_CLASS,
        "CLIENT_METHOD": client_method,
        "CALL_ARGS": call_arguments(args, call),
        "URL": _java_string(url),
        "ENVELOPE": ", ".join(_java_string(name) for name in ENVELOPE_FIELDS),
        "ENVELOPE_CLASS": _java_string(ENVELOPE_CLASS),
    }
    return _TOKEN.sub(lambda match: replacements[match.group(1)], _TEMPLATE).lstrip("\n")


def parse_result(stdout):
    """Останній непорожній рядок раннера — вердикт у JSON (FR-41); інакше — вердикт стадії `runner` (FR-43).

    Усе вище — людський лог. Рядок, що не є вердиктом, наводиться в `reason` дослівно: це найчастіше текст
    винятку Java, і причину інакше лишалося б вигадувати.
    """
    lines = [line.strip() for line in (stdout or "").splitlines() if line.strip()]
    if not lines:
        return stage_verdict("runner", "раннер не надрукував вердикту: його stdout порожній")
    last = lines[-1]
    try:
        verdict = json.loads(last)
    except (ValueError, RecursionError):
        return stage_verdict("runner", f"останній рядок раннера не є вердиктом JSON: {last}")
    if not isinstance(verdict, dict):
        return stage_verdict("runner", f"останній рядок раннера — не JSON-об'єкт вердикту: {last}")
    absent = [key for key in VERDICT_KEYS if key not in verdict]
    if absent:
        return stage_verdict("runner", f"у вердикті раннера бракує ключів {', '.join(absent)}: {last}")
    if not isinstance(verdict["green"], bool):
        return stage_verdict("runner", f"green у вердикті раннера не булеве значення: {last}")
    return verdict


@dataclass
class _Step:
    """Один запущений крок: код виходу, вивід і як він скінчився."""

    returncode: int | None
    stdout: str
    output: str
    error: str | None = None
    timed_out: bool = False


def _decoded(data):
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return data or ""


def _step(command, cwd, timeout, log, shown=None):
    """Запустити крок без шелу з лімітом часу і записати в `log` команду та весь її вивід (FR-43, NFR-5).

    Процес, що перевищив ліміт, `subprocess.run` зупиняє сам; надруковане до зупинки лишається у виводі перевірки
    (NFR-2). Програма, якої немає, — не виняток, а текст помилки ОС для вердикту стадії.
    """
    header = f"$ {shown or shlex.join(command)}"
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as expired:
        partial = _decoded(expired.stdout) + _decoded(expired.stderr)
        log.append(f"{header}\n{partial}\nзупинено на ліміті {seconds(timeout)} с — вище те, що процес устиг "
                   "надрукувати")
        return _Step(None, _decoded(expired.stdout), partial, timed_out=True)
    except (OSError, ValueError) as error:
        log.append(f"{header}\nне вдалося запустити: {error}")
        return _Step(None, "", "", error=str(error))
    log.append(f"{header}\n{done.stdout}{done.stderr}")
    return _Step(done.returncode, done.stdout, done.stdout + done.stderr)


def _verify_command(lib, verify_cmd, timeout, log):
    """Стадія `compile`: `verify_cmd` у корені бібліотеки, одна програма без шелу (FR-31)."""
    try:
        command = shlex.split(verify_cmd)
    except ValueError as error:
        raise StageFailed("compile", f"команда перевірки {verify_cmd} не розбирається shlex.split: {error}") from error
    if not command:
        raise StageFailed("compile", f"команда перевірки {verify_cmd!r} після shlex.split порожня")
    step = _step(command, lib, timeout, log)
    if step.error:
        raise StageFailed("compile", f"команду перевірки {verify_cmd} не вдалося запустити: {step.error}")
    if step.timed_out:
        raise StageFailed("compile", f"команда перевірки {verify_cmd} не завершилась за {seconds(timeout)} с і "
                                     "зупинена", timeout)
    if step.returncode != 0:
        raise StageFailed("compile", f"команда перевірки {verify_cmd} завершилась з кодом {step.returncode}")


def classpath(lib, directory, timeout=CLASSPATH_TIMEOUT_SECONDS, log=None):
    """Стадія `classpath`: класпас бібліотеки з усіма транзитивними залежностями, знятий самою ж Maven (FR-33)."""
    log = [] if log is None else log
    output = pathlib.Path(directory) / "cp.txt"
    step = _step(["mvn", "-q", "dependency:build-classpath", f"-Dmdep.outputFile={output}"], lib, timeout, log)
    if step.error:
        raise StageFailed("classpath", f"класпас не знято: програму mvn не вдалося запустити: {step.error}")
    if step.timed_out:
        raise StageFailed("classpath", f"mvn -q dependency:build-classpath не завершився за {seconds(timeout)} с і "
                                       "зупинений", timeout)
    if step.returncode != 0:
        raise StageFailed("classpath", f"класпас не зібрався: mvn -q dependency:build-classpath завершився з кодом "
                                       f"{step.returncode}")
    if not output.is_file():
        raise StageFailed("classpath", f"класпас не зібрався: mvn -q dependency:build-classpath не лишив файлу "
                                       f"{output}")
    return f"{pathlib.Path(lib) / 'target' / 'classes'}{os.pathsep}{output.read_text(encoding='utf-8').strip()}"


def _compile_runner(directory, source, path, timeout, log):
    """Стадія `javac`: раннер проти `<lib>/target/classes` і класпасу бібліотеки (FR-33)."""
    command = ["javac", "-proc:none", "-encoding", "UTF-8", "-cp", path, "-d", str(directory), str(source)]
    step = _step(command, directory, timeout, log,
                 shown=f"javac -proc:none -encoding UTF-8 -cp <класпас бібліотеки> -d {directory} {source.name}")
    if step.error:
        raise StageFailed("javac", f"раннер не скомпільовано: програму javac не вдалося запустити: {step.error}")
    if step.timed_out:
        raise StageFailed("javac", f"javac раннера не завершився за {seconds(timeout)} с і зупинений", timeout)
    if step.returncode != 0:
        raise StageFailed("javac", f"раннер не зібрався проти класів бібліотеки: javac завершився з кодом "
                                   f"{step.returncode}")


def _run_runner(directory, path, timeout, log):
    """Раннер із тим самим класпасом (FR-33); на ліміті — стадія `timeout`, навіть якщо вердикт устиг (NFR-2).

    Робочий каталог — каталог раннера: усе, що клієнт бібліотеки захоче покласти відносно поточного каталогу,
    лягає туди, а не в бібліотеку чи в репозиторій інструмента.
    """
    step = _step(["java", "-cp", f"{directory}{os.pathsep}{path}", RUNNER_CLASS], directory, timeout, log,
                 shown=f"java {RUNNER_CLASS}")
    if step.error:
        raise StageFailed("runner", f"раннер не запущено: програму java не вдалося запустити: {step.error}")
    if step.timed_out:
        raise StageFailed("timeout", f"раннер не завершився за {seconds(timeout)} с і зупинений — вердикт цього "
                                     "запуску не приймається; надруковане до зупинки — у виводі перевірки", timeout)
    return step.stdout


def run(lib, method, url, verify_cmd, *, verify_timeout=VERIFY_TIMEOUT_SECONDS,
        classpath_timeout=CLASSPATH_TIMEOUT_SECONDS, javac_timeout=JAVAC_TIMEOUT_SECONDS,
        runner_timeout=RUNNER_TIMEOUT_SECONDS):
    """Повний прогін перевірки: `verify_cmd`, каталог раннера, класпас, `javac`, раннер. Віддає (вердикт, вивід).

    Не кидає: збій будь-якої стадії — червоний вердикт стадії (FR-43). Вивід — кожна запущена команда з її stdout і
    stderr; цикл пише його в лог ітерації (FR-64). Каталог раннера прибирається після прогону, у `lib` не пишеться
    нічого (FR-44).
    """
    lib = pathlib.Path(lib).absolute()
    log = []
    directory = None
    try:
        _verify_command(lib, verify_cmd, verify_timeout, log)
        directory = runner_dir(lib)
        source = directory / f"{RUNNER_CLASS}.java"
        try:
            source.write_text(render_runner(method.model, method.client_method, method.args, url, call=method.call),
                              encoding="utf-8")
        except OSError as error:
            raise StageFailed("workdir", f"раннер не записано в {directory}: {error}") from error
        path = classpath(lib, directory, classpath_timeout, log)
        _compile_runner(directory, source, path, javac_timeout, log)
        stdout = _run_runner(directory, path, runner_timeout, log)
    except StageFailed as failed:
        return failed.verdict, "\n".join(log)
    finally:
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)
    return parse_result(stdout), "\n".join(log)
