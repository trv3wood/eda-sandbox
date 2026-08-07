module inout_probe(input logic drive, input logic value,
                   inout wire pad, output logic sampled);
  assign pad = drive ? value : 1'bz;
  assign sampled = pad;
endmodule

