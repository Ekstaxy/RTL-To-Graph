// Orthogonal object-avoiding routing with libavoid (Wybrow et al.). Text on stdin:
//   S <id> <x> <y> <w> <h>                obstacle (top-left, size)
//   P <shape id> <sides> <n>              n exclusive pins per side on that shape; sides
//                                         is a subset of "NESW" (bars: "NS")
//   C <conn id> <shape a> <shape b>       connector between any free pins of a and b
//   Q <conn id> <x1> <y1> <x2> <y2> <d1> <d2>  connector between points; d = ConnDir bits
// Out: R <conn id> x,y x,y ...
#include <iostream>
#include <map>
#include <sstream>
#include <string>

#include "libavoid/libavoid.h"

using namespace Avoid;

int main(int argc, char **argv) {
    double buffer = argc > 1 ? std::stod(argv[1]) : 8;
    double nudge = argc > 2 ? std::stod(argv[2]) : 6;
    int level = argc > 3 ? std::stoi(argv[3]) : 0;  // 0 all nudging, 1 less, 2 least
    Router *r = new Router(OrthogonalRouting);
    r->setRoutingParameter(segmentPenalty, 50);
    r->setRoutingParameter(crossingPenalty, 400);
    r->setRoutingParameter(fixedSharedPathPenalty, 0);
    r->setRoutingParameter(shapeBufferDistance, buffer);
    r->setRoutingParameter(idealNudgingDistance, nudge);
    r->setRoutingOption(nudgeOrthogonalSegmentsConnectedToShapes, level < 2);
    r->setRoutingOption(nudgeOrthogonalTouchingColinearSegments, level < 1);
    r->setRoutingOption(performUnifyingNudgingPreprocessingStep, level < 1);
    r->setRoutingOption(nudgeSharedPathsWithCommonEndPoint, level < 2);
    std::map<std::string, ShapeRef *> shapes;
    std::map<std::string, unsigned> cls;
    std::map<unsigned, std::string> names;
    std::string line;
    unsigned next = 1;
    while (std::getline(std::cin, line)) {
        std::istringstream in(line);
        std::string k;
        in >> k;
        if (k == "S") {
            std::string id;
            double x, y, w, h;
            in >> id >> x >> y >> w >> h;
            Rectangle rect(Point(x, y), Point(x + w, y + h));
            shapes[id] = new ShapeRef(r, rect);
            cls[id] = next++;
        } else if (k == "P") {
            std::string id, sides;
            int n;
            in >> id >> sides >> n;
            ShapeRef *s = shapes[id];
            for (char c : sides) {
                for (int i = 0; i < n; ++i) {
                    double f = (i + 1.0) / (n + 1.0);
                    double xo = 0, yo = 0;
                    ConnDirFlags d = ConnDirAll;
                    if (c == 'N') { xo = f; yo = ATTACH_POS_TOP; d = ConnDirUp; }
                    if (c == 'S') { xo = f; yo = ATTACH_POS_BOTTOM; d = ConnDirDown; }
                    if (c == 'W') { xo = ATTACH_POS_LEFT; yo = f; d = ConnDirLeft; }
                    if (c == 'E') { xo = ATTACH_POS_RIGHT; yo = f; d = ConnDirRight; }
                    ShapeConnectionPin *p = new ShapeConnectionPin(s, cls[id], xo, yo, true, 0, d);
                    p->setExclusive(true);
                }
            }
        } else if (k == "C") {
            std::string id, a, b;
            in >> id >> a >> b;
            ConnRef *c = new ConnRef(r, ConnEnd(shapes[a], cls[a]), ConnEnd(shapes[b], cls[b]));
            names[c->id()] = id;
        } else if (k == "Q") {
            std::string id;
            double x1, y1, x2, y2;
            unsigned d1, d2;
            in >> id >> x1 >> y1 >> x2 >> y2 >> d1 >> d2;
            ConnRef *c = new ConnRef(r, ConnEnd(Point(x1, y1), d1), ConnEnd(Point(x2, y2), d2));
            names[c->id()] = id;
        }
    }
    r->processTransaction();
    for (ConnRef *c : r->connRefs) {
        const PolyLine &route = c->displayRoute();
        std::cout << "R " << names[c->id()];
        for (size_t i = 0; i < route.size(); ++i) std::cout << " " << route.ps[i].x << "," << route.ps[i].y;
        std::cout << "\n";
    }
    delete r;
    return 0;
}
