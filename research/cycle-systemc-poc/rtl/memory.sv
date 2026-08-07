module memory(input logic clk, write_enable,
              input logic [3:0] address,
              input logic [15:0] write_data,
              output logic [15:0] read_data);
  logic [15:0] storage [0:15];
  always_ff @(posedge clk)
    if (write_enable) storage[address] <= write_data;
  assign read_data = storage[address];
endmodule

