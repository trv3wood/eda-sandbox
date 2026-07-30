/*
 * 在 VCS elaboration 完成后的零时刻导出结构事实。
 *
 * 该插件只读取 VPI 对象，不推进仿真时间，也不推断 RTL 行为。Python producer
 * 会继续完成路径归一化、输入摘要校验和 canonical graph 门禁。
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "vpi_user.h"

static FILE *output_stream;

static void json_string(const char *value)
{
    const unsigned char *cursor;

    if (value == NULL) {
        fputs("null", output_stream);
        return;
    }
    fputc('"', output_stream);
    for (cursor = (const unsigned char *)value; *cursor != '\0'; ++cursor) {
        switch (*cursor) {
        case '"':
            fputs("\\\"", output_stream);
            break;
        case '\\':
            fputs("\\\\", output_stream);
            break;
        case '\b':
            fputs("\\b", output_stream);
            break;
        case '\f':
            fputs("\\f", output_stream);
            break;
        case '\n':
            fputs("\\n", output_stream);
            break;
        case '\r':
            fputs("\\r", output_stream);
            break;
        case '\t':
            fputs("\\t", output_stream);
            break;
        default:
            if (*cursor < 0x20) {
                fprintf(output_stream, "\\u%04x", (unsigned int)*cursor);
            } else {
                fputc(*cursor, output_stream);
            }
        }
    }
    fputc('"', output_stream);
}

static void property_string(const char *name, PLI_INT32 property, vpiHandle object)
{
    fprintf(output_stream, "\"%s\":", name);
    json_string(vpi_get_str(property, object));
}

static void location(vpiHandle object)
{
    fputc(',', output_stream);
    property_string("path", vpiFile, object);
    fprintf(output_stream, ",\"line\":%d", vpi_get(vpiLineNo, object));
}

static void named_object(vpiHandle object)
{
    fputc('{', output_stream);
    property_string("name", vpiName, object);
    location(object);
    fprintf(output_stream, ",\"size\":%d}", vpi_get(vpiSize, object));
}

static void object_array(PLI_INT32 relation, vpiHandle parent)
{
    vpiHandle iterator;
    vpiHandle object;
    int first = 1;

    fputc('[', output_stream);
    iterator = vpi_iterate(relation, parent);
    while (iterator != NULL && (object = vpi_scan(iterator)) != NULL) {
        if (!first) {
            fputc(',', output_stream);
        }
        named_object(object);
        first = 0;
    }
    fputc(']', output_stream);
}

static const char *direction_name(PLI_INT32 direction)
{
    switch (direction) {
    case vpiInput:
        return "input";
    case vpiOutput:
        return "output";
    case vpiInout:
        return "inout";
#ifdef vpiMixedIO
    case vpiMixedIO:
        return "mixed";
#endif
#ifdef vpiNoDirection
    case vpiNoDirection:
        return "none";
#endif
    default:
        return "unknown";
    }
}

static void port_array(vpiHandle module)
{
    vpiHandle iterator;
    vpiHandle object;
    int first = 1;

    fputc('[', output_stream);
    iterator = vpi_iterate(vpiPort, module);
    while (iterator != NULL && (object = vpi_scan(iterator)) != NULL) {
        if (!first) {
            fputc(',', output_stream);
        }
        fputc('{', output_stream);
        property_string("name", vpiName, object);
        location(object);
        fprintf(
            output_stream,
            ",\"size\":%d,\"direction\":",
            vpi_get(vpiSize, object)
        );
        json_string(direction_name(vpi_get(vpiDirection, object)));
        fputc('}', output_stream);
        first = 0;
    }
    fputc(']', output_stream);
}

static void signal_array(vpiHandle module)
{
    vpiHandle iterator;
    vpiHandle object;
    int first = 1;
    PLI_INT32 relations[] = {
        vpiNet,
        vpiReg,
#ifdef vpiLogicVar
        vpiLogicVar,
#endif
    };
    size_t index;

    fputc('[', output_stream);
    for (index = 0; index < sizeof(relations) / sizeof(relations[0]); ++index) {
        iterator = vpi_iterate(relations[index], module);
        while (iterator != NULL && (object = vpi_scan(iterator)) != NULL) {
            if (!first) {
                fputc(',', output_stream);
            }
            named_object(object);
            first = 0;
        }
    }
    fputc(']', output_stream);
}

static void module_object(vpiHandle module);

static void child_modules(vpiHandle module)
{
    vpiHandle iterator;
    vpiHandle child;
    int first = 1;

    fputc('[', output_stream);
    iterator = vpi_iterate(vpiModule, module);
    while (iterator != NULL && (child = vpi_scan(iterator)) != NULL) {
        if (!first) {
            fputc(',', output_stream);
        }
        module_object(child);
        first = 0;
    }
    fputc(']', output_stream);
}

static void import_array(vpiHandle module)
{
    /*
     * vpiImport 并非所有历史 VCS 头文件都公开。缺少该关系时输出空数组，
     * 研发网 capability fixture 会明确暴露版本差异。
     */
#ifdef vpiImport
    object_array(vpiImport, module);
#else
    (void)module;
    fputs("[]", output_stream);
#endif
}

static void module_object(vpiHandle module)
{
    fputc('{', output_stream);
    property_string("name", vpiFullName, module);
    fputc(',', output_stream);
    property_string("definition", vpiDefName, module);
    location(module);
    fputs(",\"ports\":", output_stream);
    port_array(module);
    fputs(",\"parameters\":", output_stream);
    object_array(vpiParameter, module);
    fputs(",\"signals\":", output_stream);
    signal_array(module);
    fputs(",\"imports\":", output_stream);
    import_array(module);
    fputs(",\"instances\":", output_stream);
    child_modules(module);
    fputc('}', output_stream);
}

static void package_array(void)
{
    vpiHandle iterator;
    vpiHandle object;
    int first = 1;

    fputc('[', output_stream);
#ifdef vpiPackage
    iterator = vpi_iterate(vpiPackage, NULL);
    while (iterator != NULL && (object = vpi_scan(iterator)) != NULL) {
        if (!first) {
            fputc(',', output_stream);
        }
        named_object(object);
        first = 0;
    }
#else
    iterator = NULL;
    object = NULL;
    (void)iterator;
    (void)object;
    (void)first;
#endif
    fputc(']', output_stream);
}

static PLI_INT32 export_structure(p_cb_data callback_data)
{
    vpiHandle iterator;
    vpiHandle module;
    const char *output_path;
    int first = 1;

    (void)callback_data;
    output_path = getenv("TLM_GRAPH_OUTPUT");
    if (output_path == NULL || output_path[0] == '\0') {
        vpi_printf("ERROR: TLM_GRAPH_OUTPUT is not set\n");
        vpi_control(vpiFinish, 1);
        return 0;
    }
    output_stream = fopen(output_path, "w");
    if (output_stream == NULL) {
        vpi_printf("ERROR: cannot open TLM_GRAPH_OUTPUT %s\n", output_path);
        vpi_control(vpiFinish, 1);
        return 0;
    }

    fputs("{\"top_modules\":[", output_stream);
    iterator = vpi_iterate(vpiModule, NULL);
    while (iterator != NULL && (module = vpi_scan(iterator)) != NULL) {
        if (!first) {
            fputc(',', output_stream);
        }
        module_object(module);
        first = 0;
    }
    fputs("],\"packages\":", output_stream);
    package_array();
    fputs("}\n", output_stream);
    if (fclose(output_stream) != 0) {
        vpi_printf("ERROR: failed to close TLM_GRAPH_OUTPUT %s\n", output_path);
        vpi_control(vpiFinish, 1);
        return 0;
    }
    output_stream = NULL;
    vpi_control(vpiFinish, 0);
    return 0;
}

void tlm_graph_register(void)
{
    s_cb_data callback;

    memset(&callback, 0, sizeof(callback));
    callback.reason = cbStartOfSimulation;
    callback.cb_rtn = export_structure;
    vpi_register_cb(&callback);
}
