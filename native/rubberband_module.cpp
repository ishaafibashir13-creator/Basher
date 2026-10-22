// SPDX-License-Identifier: GPL-2.0-or-later
// Small CPython streaming adapter for the unmodified Rubber Band Library R3.
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <rubberband/RubberBandStretcher.h>
#include <vector>
#include <map>
#include <memory>
#include <cstring>
#include <stdexcept>
using RubberBand::RubberBandStretcher;
static constexpr const char *name = "vocalmidi.RubberBandR3";
static RubberBandStretcher *get(PyObject *c) {
    return static_cast<RubberBandStretcher *>(PyCapsule_GetPointer(c, name));
}
static void destroy(PyObject *c) { delete get(c); }
static PyObject *create(PyObject *, PyObject *args) {
    int rate; Py_ssize_t input, output; PyObject *anchors;
    if (!PyArg_ParseTuple(args, "innO", &rate, &input, &output, &anchors)) return nullptr;
    if (rate < 8000 || input <= 0 || output <= 0) {
        PyErr_SetString(PyExc_ValueError, "Invalid sample rate or length"); return nullptr;
    }
    PyObject *seq = PySequence_Fast(anchors, "Expected time-map pairs");
    if (!seq) return nullptr;
    std::map<size_t, size_t> map;
    Py_ssize_t lastA=-1, lastB=-1;
    for (Py_ssize_t i=0; i<PySequence_Fast_GET_SIZE(seq); ++i) {
        PyObject *pair=PySequence_Fast_GET_ITEM(seq,i); Py_ssize_t a,b;
        if (!PyArg_ParseTuple(pair,"nn",&a,&b)) { Py_DECREF(seq); return nullptr; }
        if (a<0 || b<0 || a>input || b>output || a<=lastA || b<=lastB) {
            Py_DECREF(seq); PyErr_SetString(PyExc_ValueError,"Time-map anchors must increase strictly"); return nullptr;
        }
        // R3 treats the first entry as a ratio from the implicit (0,0).
        // Passing (0,0) itself would produce 0/0 in upstream 4.0.0.
        if (a>0) map[size_t(a)]=size_t(b); lastA=a; lastB=b;
    }
    Py_DECREF(seq);
    try {
        auto rb=std::unique_ptr<RubberBandStretcher>(new RubberBandStretcher(
            size_t(rate),1,RubberBandStretcher::OptionProcessOffline |
            RubberBandStretcher::OptionEngineFiner | RubberBandStretcher::OptionThreadingNever,
            double(output)/double(input),1.0));
        if (rb->getEngineVersion()!=3) throw std::runtime_error("R3 engine unavailable");
        rb->setExpectedInputDuration(size_t(input)); rb->setMaxProcessSize(4096);
        rb->setKeyFrameMap(map);
        PyObject *capsule=PyCapsule_New(rb.get(),name,destroy);
        if (capsule) rb.release();
        return capsule;
    } catch(const std::exception &e) { PyErr_SetString(PyExc_RuntimeError,e.what()); return nullptr; }
}
static PyObject *feed(PyObject *args, bool study) {
    PyObject *capsule; Py_buffer data; int final;
    if (!PyArg_ParseTuple(args,"Oy*p",&capsule,&data,&final)) return nullptr;
    auto *rb=get(capsule);
    if (!rb) { PyBuffer_Release(&data); return nullptr; }
    if (data.len%sizeof(float) || data.len/sizeof(float)>4096) {
        PyBuffer_Release(&data); PyErr_SetString(PyExc_ValueError,"Expected at most 4096 float32 samples"); return nullptr;
    }
    std::vector<float> x(size_t(data.len)/sizeof(float));
    if (data.len) std::memcpy(x.data(),data.buf,size_t(data.len));
    PyBuffer_Release(&data);
    const float *channels[1]={x.data()};
    try {
        if (study) rb->study(channels,x.size(),final);
        else rb->process(channels,x.size(),final);
    } catch(const std::exception &e) { PyErr_SetString(PyExc_RuntimeError,e.what()); return nullptr; }
    Py_RETURN_NONE;
}
static PyObject *study(PyObject *, PyObject *args) { return feed(args,true); }
static PyObject *process(PyObject *, PyObject *args) { return feed(args,false); }
static PyObject *available(PyObject *, PyObject *c) {
    auto *rb=get(c); return rb ? PyLong_FromLong(rb->available()) : nullptr;
}
static PyObject *retrieve(PyObject *, PyObject *c) {
    auto *rb=get(c); if (!rb) return nullptr;
    int n=rb->available(); if (n<=0) return PyBytes_FromStringAndSize("",0);
    n=std::min(n,8192); std::vector<float> y(n); float *channels[1]={y.data()};
    size_t got=rb->retrieve(channels,size_t(n));
    return PyBytes_FromStringAndSize(reinterpret_cast<const char *>(y.data()),Py_ssize_t(got*sizeof(float)));
}
static PyMethodDef methods[]={
    {"create",create,METH_VARARGS,"Create an offline R3 stretcher with a sample-frame map."},
    {"study",study,METH_VARARGS,"First-pass analysis."},
    {"process",process,METH_VARARGS,"Second-pass rendering."},
    {"available",available,METH_O,"Available frames; -1 at end."},
    {"retrieve",retrieve,METH_O,"Retrieve native float32 samples."},
    {nullptr,nullptr,0,nullptr}
};
static PyModuleDef module={PyModuleDef_HEAD_INIT,"_native","Rubber Band 4.0.0 R3 streaming adapter",-1,methods};
PyMODINIT_FUNC PyInit__native() { return PyModule_Create(&module); }
